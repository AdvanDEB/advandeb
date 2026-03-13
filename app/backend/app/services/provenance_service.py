"""
Provenance service — builds Answer → Facts → Chunks → Documents chains.
"""
from typing import Dict, Any, Optional
from bson import ObjectId

from app.core.database import get_database


class ProvenanceService:
    """Service for retrieving provenance chains for cited content."""

    def __init__(self):
        self.db = get_database()

    async def get_provenance(self, citation_id: str) -> Optional[Dict[str, Any]]:
        """
        Return the full provenance chain for a citation.

        The chain structure:
          answer_excerpt → facts_used → source_chunks → documents

        Citation documents are stored by the KB ingestion pipeline in the
        `provenance` collection. Falls back gracefully when data is sparse.
        """
        # Attempt to load from dedicated provenance collection first
        record = await self.db.provenance.find_one({"citation_id": citation_id})

        if record:
            record.pop("_id", None)
            return record

        # Fallback: reconstruct from chunks + documents collections
        return await self._reconstruct_provenance(citation_id)

    async def _reconstruct_provenance(self, citation_id: str) -> Optional[Dict[str, Any]]:
        """Build a provenance record from raw chunk and document data."""
        # Try to find the chunk directly by citation_id / chunk_id
        chunk = await self.db.document_chunks.find_one(
            {"$or": [{"_id": ObjectId(citation_id)}, {"citation_id": citation_id}]}
            if self._is_object_id(citation_id)
            else {"citation_id": citation_id}
        )

        if not chunk:
            return None

        chunk_id = str(chunk.get("_id", ""))
        doc_id = str(chunk.get("document_id", ""))

        # Fetch parent document
        document = None
        if doc_id:
            doc = await self.db.documents.find_one({"_id": ObjectId(doc_id)} if self._is_object_id(doc_id) else {"_id": doc_id})
            if doc:
                document = {
                    "id": str(doc.get("_id", "")),
                    "title": doc.get("title", "Unknown"),
                    "authors": doc.get("authors", ""),
                    "year": doc.get("year"),
                    "url": doc.get("url"),
                }

        return {
            "citation_id": citation_id,
            "answer": {
                "excerpt": chunk.get("text", "")[:200],
            },
            "facts": chunk.get("facts", []),
            "chunks": [
                {
                    "id": chunk_id,
                    "text": chunk.get("text", ""),
                    "score": chunk.get("relevance_score", 1.0),
                    "page": chunk.get("page"),
                }
            ],
            "documents": [document] if document else [],
        }

    async def get_chunk_context(self, chunk_id: str, window: int = 2) -> Dict[str, Any]:
        """Return a chunk plus its neighboring chunks for context."""
        chunk = await self.db.document_chunks.find_one(
            {"_id": ObjectId(chunk_id)} if self._is_object_id(chunk_id) else {"chunk_id": chunk_id}
        )
        if not chunk:
            return {"chunk": None, "context": []}

        doc_id = str(chunk.get("document_id", ""))
        chunk_index = chunk.get("chunk_index", 0)

        neighbors = []
        if doc_id:
            cursor = self.db.document_chunks.find(
                {
                    "document_id": doc_id,
                    "chunk_index": {
                        "$gte": max(0, chunk_index - window),
                        "$lte": chunk_index + window,
                    },
                }
            ).sort("chunk_index", 1)
            async for neighbor in cursor:
                neighbors.append({
                    "id": str(neighbor["_id"]),
                    "text": neighbor.get("text", ""),
                    "chunk_index": neighbor.get("chunk_index"),
                    "is_target": str(neighbor["_id"]) == chunk_id,
                })

        return {
            "chunk": {
                "id": chunk_id,
                "text": chunk.get("text", ""),
                "score": chunk.get("relevance_score", 1.0),
            },
            "context": neighbors,
        }

    @staticmethod
    def _is_object_id(value: str) -> bool:
        try:
            ObjectId(value)
            return True
        except Exception:
            return False
