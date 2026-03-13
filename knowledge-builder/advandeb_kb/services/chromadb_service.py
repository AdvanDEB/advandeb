"""
ChromaDBService — persistent embedded vector store.

Uses ChromaDB in embedded (in-process) mode: no separate server needed.
Data is persisted to CHROMA_PERSIST_DIR (default: ./data/chromadb).

Collection: advandeb_chunks
    - id:        chunk_id (str)
    - embedding: float vector (from EmbeddingService)
    - document:  chunk text
    - metadata:  {document_id, chunk_index, char_start, char_end, ...}
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from advandeb_kb.config.settings import settings

logger = logging.getLogger(__name__)


class ChromaDBService:
    """
    Manages vector storage and similarity search using embedded ChromaDB.

    Usage:
        svc = ChromaDBService()
        svc.add_chunk("chunk_abc", "text here", [0.1, 0.2, ...], {"document_id": "..."})
        results = svc.search([0.1, 0.2, ...], n_results=10)
    """

    def __init__(
        self,
        persist_dir: Optional[str] = None,
        collection_name: Optional[str] = None,
    ):
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        self.collection_name = collection_name or settings.CHROMA_COLLECTION
        self._client = None
        self._collection = None

    # ------------------------------------------------------------------
    # Lazy client init
    # ------------------------------------------------------------------

    def _ensure_connected(self):
        if self._client is None:
            import chromadb

            os.makedirs(self.persist_dir, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self.persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "ChromaDB connected (embedded). persist_dir=%s collection=%s count=%d",
                self.persist_dir,
                self.collection_name,
                self._collection.count(),
            )

    @property
    def collection(self):
        self._ensure_connected()
        return self._collection

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add_chunk(
        self,
        chunk_id: str,
        text: str,
        embedding: list[float],
        metadata: dict,
    ) -> None:
        """Add or replace a single chunk with its embedding."""
        self._ensure_connected()
        # ChromaDB upsert: add if missing, replace if exists
        self._collection.upsert(
            ids=[chunk_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
        )

    def add_chunks_batch(
        self,
        chunk_ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        """Batch upsert for efficiency during ingestion."""
        if not chunk_ids:
            return
        self._ensure_connected()
        self._collection.upsert(
            ids=chunk_ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )
        logger.debug("ChromaDB: upserted %d chunks", len(chunk_ids))

    def delete_chunk(self, chunk_id: str) -> None:
        self._ensure_connected()
        self._collection.delete(ids=[chunk_id])

    def delete_chunks_by_document(self, document_id: str) -> None:
        """Remove all chunks belonging to a document."""
        self._ensure_connected()
        self._collection.delete(where={"document_id": document_id})
        logger.debug("ChromaDB: deleted chunks for document %s", document_id)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """
        Cosine similarity search.

        Returns a list of dicts:
            [{"id": "...", "text": "...", "metadata": {...}, "distance": 0.12}, ...]
        """
        self._ensure_connected()

        kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": min(n_results, max(1, self._collection.count())),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        raw = self._collection.query(**kwargs)

        results = []
        for i, chunk_id in enumerate(raw["ids"][0]):
            results.append(
                {
                    "id": chunk_id,
                    "text": raw["documents"][0][i],
                    "metadata": raw["metadatas"][0][i],
                    "distance": raw["distances"][0][i],
                }
            )
        return results

    def get_chunk(self, chunk_id: str) -> Optional[dict]:
        """Fetch a single chunk by ID."""
        self._ensure_connected()
        raw = self._collection.get(ids=[chunk_id], include=["documents", "metadatas"])
        if not raw["ids"]:
            return None
        return {
            "id": raw["ids"][0],
            "text": raw["documents"][0],
            "metadata": raw["metadatas"][0],
        }

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def count(self) -> int:
        return self.collection.count()

    def stats(self) -> dict:
        return {
            "collection": self.collection_name,
            "persist_dir": self.persist_dir,
            "count": self.count(),
        }
