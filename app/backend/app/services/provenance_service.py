"""
Provenance service — builds Answer → Facts → Chunks → Documents chains.

The citation IDs coming from the chatbot can be in several formats:
  - "chunk:<key>"  — real text chunk _key in ArangoDB
  - "fact:<key>"   — synthetic graph fact citation
  - "sf:<key>"     — synthetic stylized-fact citation
  - legacy raw chunk ids / "gfact_<key>" / "gsf_<key>"

All lookups target the ArangoDB KB (advandeb_kb).
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from app.core.database import get_arango_db
from advandeb_kb.models.chat import parse_citation_id, strip_collection_prefix

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="provenance-svc")


class ProvenanceService:
    """Service for retrieving provenance chains for cited content."""

    def __init__(self):
        self.arango = get_arango_db()

    async def _run(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))

    async def get_provenance(self, citation_id: str) -> Optional[Dict[str, Any]]:
        """
        Return the full provenance chain for a citation.

        The chain structure:
          answer_excerpt → facts_used → source_chunks → documents

        Tries in order:
          1. Dedicated provenance collection (if KB ingestion pipeline populated it)
          2. Reconstruct from chunks / facts / stylized_facts collections
        """
        # 1. Dedicated provenance collection
        def _get_provenance_record():
            rows = self.arango.aql(
                "FOR doc IN provenance_traces FILTER doc.citation_id == @cid LIMIT 1 RETURN doc",
                {"cid": citation_id},
            )
            return rows[0] if rows else None

        record = await self._run(_get_provenance_record)
        if record:
            record.pop("_id", None)
            record.pop("_key", None)
            record.pop("_rev", None)
            return record

        # 2. Reconstruct from raw collections
        return await self._reconstruct_provenance(citation_id)

    async def _reconstruct_provenance(self, citation_id: str) -> Optional[Dict[str, Any]]:
        """Build a provenance record from raw chunk / fact data in ArangoDB."""
        source_type, raw_id = parse_citation_id(citation_id)

        if source_type == "fact":
            return await self._provenance_from_fact(raw_id, citation_id)

        if source_type == "stylized_fact":
            return await self._provenance_from_stylized_fact(raw_id, citation_id)

        if source_type == "external_document":
            return None

        chunk = await self._find_chunk(raw_id or citation_id)
        if chunk:
            return await self._provenance_from_chunk(chunk, citation_id)

        return None

    # ------------------------------------------------------------------
    # Chunk lookup helpers
    # ------------------------------------------------------------------

    async def _find_chunk(self, cid: str) -> Optional[dict]:
        """Look up a text chunk by _key or chunk_id field."""
        def _lookup():
            # Try by _key first
            doc = self.arango.get("chunks", cid)
            if doc:
                return doc
            # Try by chunk_id field
            rows = self.arango.aql(
                "FOR doc IN chunks FILTER doc.chunk_id == @cid LIMIT 1 RETURN doc",
                {"cid": cid},
            )
            return rows[0] if rows else None
        return await self._run(_lookup)

    async def _provenance_from_chunk(self, chunk: dict, citation_id: str) -> dict:
        chunk_key = chunk.get("_key", "")
        doc_id = chunk.get("document_id", "")
        document = await self._fetch_document(doc_id)
        return {
            "citation_id": citation_id,
            "answer": {"excerpt": chunk.get("text", "")[:200]},
            "facts": chunk.get("facts", []),
            "chunks": [{
                "id": chunk_key,
                "text": chunk.get("text", ""),
                "score": chunk.get("relevance_score", 1.0),
                "page": chunk.get("page"),
            }],
            "documents": [document] if document else [],
        }

    # ------------------------------------------------------------------
    # Graph fact / stylized fact helpers
    # ------------------------------------------------------------------

    async def _provenance_from_fact(self, raw_id: str, citation_id: str) -> Optional[dict]:
        """Build provenance for a KB fact."""
        def _lookup():
            return self.arango.get("facts", raw_id)
        fact = await self._run(_lookup)
        if not fact:
            return None
        doc_id = strip_collection_prefix(str(fact.get("document_id", "")))
        document = await self._fetch_document(doc_id)
        return {
            "citation_id": citation_id,
            "answer": {"excerpt": fact.get("content", "")[:200]},
            "facts": [{"text": fact.get("content", ""), "confidence": fact.get("confidence")}],
            "chunks": [{
                "id": citation_id,
                "text": fact.get("content", ""),
                "score": 1.0,
                "page": None,
            }],
            "documents": [document] if document else [],
        }

    async def _provenance_from_stylized_fact(self, raw_id: str, citation_id: str) -> Optional[dict]:
        """Build provenance for a stylized fact."""
        def _lookup():
            return self.arango.get("stylized_facts", raw_id)
        sf = await self._run(_lookup)
        if not sf:
            return None
        doc_id = strip_collection_prefix(str(sf.get("document_id", "")))
        document = await self._fetch_document(doc_id)
        return {
            "citation_id": citation_id,
            "answer": {"excerpt": sf.get("statement", "")[:200]},
            "facts": [{"text": sf.get("statement", "")}],
            "chunks": [{
                "id": citation_id,
                "text": sf.get("statement", ""),
                "score": 1.0,
                "page": None,
            }],
            "documents": [document] if document else [],
        }

    # ------------------------------------------------------------------
    # Document lookup
    # ------------------------------------------------------------------

    async def _fetch_document(self, doc_id: str) -> Optional[dict]:
        doc_key = strip_collection_prefix(doc_id)
        if not doc_key:
            return None
        def _lookup():
            return self.arango.get("documents", doc_key)
        doc = await self._run(_lookup)
        if not doc:
            return None
        return {
            "id": doc.get("_key", ""),
            "title": doc.get("title", "Unknown"),
            "authors": doc.get("authors", ""),
            "year": doc.get("year"),
            "url": doc.get("url") or (f"https://doi.org/{doc['doi']}" if doc.get("doi") else None),
        }

    # ------------------------------------------------------------------
    # Chunk context
    # ------------------------------------------------------------------

    async def get_chunk_context(self, chunk_id: str, window: int = 2) -> Dict[str, Any]:
        """Return a chunk plus its neighboring chunks for context."""
        chunk = await self._find_chunk(chunk_id)
        if not chunk:
            return {"chunk": None, "context": []}

        doc_id = chunk.get("document_id", "")
        chunk_index = chunk.get("chunk_index", 0)

        def _neighbors():
            if not doc_id:
                return []
            return self.arango.aql(
                """
                FOR doc IN chunks
                    FILTER doc.document_id == @doc_id
                       AND doc.chunk_index >= @min_idx
                       AND doc.chunk_index <= @max_idx
                    SORT doc.chunk_index ASC
                    RETURN doc
                """,
                {
                    "doc_id": doc_id,
                    "min_idx": max(0, chunk_index - window),
                    "max_idx": chunk_index + window,
                },
            )

        neighbor_docs = await self._run(_neighbors)
        neighbors = []
        for neighbor in neighbor_docs:
            nkey = neighbor.get("_key", "")
            neighbors.append({
                "id": nkey,
                "text": neighbor.get("text", ""),
                "chunk_index": neighbor.get("chunk_index"),
                "is_target": nkey == chunk.get("_key", ""),
            })

        return {
            "chunk": {
                "id": chunk_id,
                "text": chunk.get("text", ""),
                "score": chunk.get("relevance_score", 1.0),
            },
            "context": neighbors,
        }
