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
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from bson import ObjectId

from app.core.database import get_arango_db, get_database, get_kb_database
from advandeb_kb.models.chat import parse_citation_id, strip_collection_prefix

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="provenance-svc")

_OBJECT_ID_RE = re.compile(r"^[0-9a-f]{24}$")

# Match a document by the tail of its source_path ("<folder>/<file>.pdf") or, as a
# weaker fallback, just the filename. Used to recover the source document for chunks
# whose document_id does not resolve directly (legacy `doc_*` ingestion lineage).
_DOC_BY_SOURCE_PATH_AQL = """
LET parts = SPLIT(@sp, '/')
LET filename = parts[-1]
LET tail = LENGTH(parts) >= 2 ? CONCAT(parts[-2], '/', parts[-1]) : filename
FOR d IN documents
    FILTER d.source_path != null
    LET sp = d.source_path
    LET exact = (sp == tail OR RIGHT(sp, LENGTH(tail) + 1) == CONCAT('/', tail))
    LET byname = (LAST(SPLIT(sp, '/')) == filename)
    FILTER exact OR byname
    SORT exact ? 0 : 1
    LIMIT 1
    RETURN d
"""


class ProvenanceService:
    """Service for retrieving provenance chains for cited content."""

    def __init__(self):
        self.arango = get_arango_db()
        self._app_db = get_database()       # MongoDB advandeb — document metadata
        self._kb_db = get_kb_database()      # MongoDB KB — document metadata (fallback)

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

    async def enrich_citations(self, citations: list) -> list:
        """Attach source-document provenance to each citation in place.

        For every citation that resolves to a source document via
        ``get_provenance``, fill ``document_id``/``title``/``authors``/``year``/
        ``url`` (and ``doi`` when derivable from the url). Idempotent: a citation
        that already has a ``title`` is left untouched, so this is safe to call
        more than once along the response path. Citations with no local
        provenance (e.g. ``external:`` sources) are returned unchanged.
        """
        if not citations:
            return citations
        for cit in citations:
            if not isinstance(cit, dict) or cit.get("title"):
                continue
            citation_id = cit.get("citation_id")
            if not citation_id:
                continue
            try:
                prov = await self.get_provenance(citation_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("enrich_citations: provenance lookup failed for %s: %s",
                               citation_id, exc)
                continue
            docs = (prov or {}).get("documents") or []
            if not docs:
                continue
            doc = docs[0]
            if not cit.get("document_id"):
                cit["document_id"] = doc.get("id")
            cit["title"] = doc.get("title")
            authors = doc.get("authors")
            if isinstance(authors, str):
                authors = [authors] if authors.strip() else []
            elif not isinstance(authors, list):
                authors = []
            if authors:
                cit["authors"] = authors
            if doc.get("year") is not None:
                cit["year"] = doc.get("year")
            url = doc.get("url")
            if url:
                cit["url"] = url
                if not cit.get("doi") and "doi.org/" in url:
                    cit["doi"] = url.split("doi.org/", 1)[1]
        return citations

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
        document = await self._fetch_document(doc_id, source_path=chunk.get("source_path"))
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

    async def _fetch_document(
        self, doc_id: str, source_path: Optional[str] = None
    ) -> Optional[dict]:
        """Resolve a cited chunk/fact to its source document.

        Chunk citations come from two ingestion lineages with different ID
        schemes, and not every ``document_id`` resolves directly in ArangoDB.
        Resolution is therefore attempted in order:

          1. ArangoDB ``documents`` by key (the common, rich case).
          2. MongoDB by ObjectId — recovers documents missing from ArangoDB and
             yields a ``source_path`` to upgrade to a richer record.
          3. ArangoDB ``documents`` matched by ``source_path`` — recovers the
             rich record for the legacy ``doc_*`` lineage (which has no resolvable
             ``document_id``) and upgrades thin MongoDB records.
          4. The thin MongoDB record, if nothing richer was found.
        """
        doc_key = strip_collection_prefix(doc_id)

        # 1. ArangoDB by key
        if doc_key:
            doc = await self._run(lambda: self.arango.get("documents", doc_key))
            if doc:
                return self._shape_document(doc)

        # 2. MongoDB by ObjectId (also a source of source_path for step 3)
        mongo_doc = await self._fetch_mongo_document(doc_key)
        effective_path = source_path or (mongo_doc.get("source_path") if mongo_doc else None)

        # 3. Richer record matched by source_path — ArangoDB first, then MongoDB.
        if effective_path:
            rich = await self._fetch_document_by_source_path(effective_path)
            if rich:
                return rich
            mongo_by_path = await self._fetch_mongo_document_by_source_path(effective_path)
            if mongo_by_path:
                return self._shape_document(mongo_by_path)

        # 4. Fall back to the thin MongoDB record
        if mongo_doc:
            return self._shape_document(mongo_doc)

        return None

    async def _fetch_mongo_document(self, doc_key: str) -> Optional[dict]:
        """Look up a document by ObjectId in the app then KB MongoDB databases."""
        if not doc_key or not _OBJECT_ID_RE.match(doc_key):
            return None
        try:
            oid = ObjectId(doc_key)
        except Exception:
            return None
        for db in (self._app_db, self._kb_db):
            if db is None:
                continue
            try:
                doc = await db.documents.find_one({"_id": oid})
            except Exception as exc:
                logger.warning("_fetch_mongo_document lookup failed: %s", exc)
                doc = None
            if doc:
                return doc
        return None

    async def _fetch_document_by_source_path(self, source_path: str) -> Optional[dict]:
        """Match an ArangoDB document by the tail/filename of its source_path."""
        if not source_path:
            return None
        rows = await self._run(
            lambda: self.arango.aql(_DOC_BY_SOURCE_PATH_AQL, {"sp": source_path})
        )
        if not rows:
            return None
        return self._shape_document(rows[0])

    async def _fetch_mongo_document_by_source_path(self, source_path: str) -> Optional[dict]:
        """Match a MongoDB document by the tail/filename of its source_path.

        MongoDB stores source_path relative ("<folder>/<file>.pdf") while chunk
        source paths may be absolute, so match is anchored at the end of the
        stored value: prefer "<folder>/<file>", fall back to bare filename.
        """
        parts = str(source_path).replace("\\", "/").split("/")
        filename = parts[-1]
        if not filename:
            return None
        tail = "/".join(parts[-2:]) if len(parts) >= 2 else filename
        patterns = [re.compile(re.escape(tail) + "$")]
        if tail != filename:
            patterns.append(re.compile(re.escape(filename) + "$"))
        for db in (self._app_db, self._kb_db):
            if db is None:
                continue
            for pat in patterns:
                try:
                    doc = await db.documents.find_one({"source_path": pat})
                except Exception as exc:
                    logger.warning("_fetch_mongo_document_by_source_path failed: %s", exc)
                    doc = None
                if doc:
                    return doc
        return None

    @staticmethod
    def _shape_document(doc: dict) -> dict:
        """Normalise an ArangoDB or MongoDB document into the trail's doc shape."""
        did = doc.get("_key") or str(doc.get("_id") or "")
        doi = doc.get("doi")
        doi = doi if doi and str(doi) != "None" else None
        return {
            "id": did,
            "title": doc.get("title") or "Unknown",
            "authors": doc.get("authors") or "",
            "year": doc.get("year"),
            "url": doc.get("url") or (f"https://doi.org/{doi}" if doi else None),
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
