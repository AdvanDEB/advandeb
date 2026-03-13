"""
Celery tasks for async embedding pipeline.

embed_document_async:
    Fetches a document from MongoDB, chunks the text, embeds each chunk
    via EmbeddingService, and stores vectors in ChromaDB.
    Optionally creates chunk→document edges in ArangoDB if available.

embed_batch_async:
    Queues embed_document_async for a list of document IDs.

re_embed_all:
    Re-embeds all completed documents (for model upgrades or re-indexing).
"""

import logging
from datetime import datetime
from typing import Optional

from bson import ObjectId

from celery_app import celery_app
from advandeb_kb.config.settings import settings
from advandeb_kb.database.mongodb import get_sync_db
from advandeb_kb.services.chunking_service import ChunkingService
from advandeb_kb.services.embedding_service import EmbeddingService
from advandeb_kb.services.chromadb_service import ChromaDBService

logger = logging.getLogger(__name__)

# Module-level singletons — loaded once per worker process
_chunker: Optional[ChunkingService] = None
_embedder: Optional[EmbeddingService] = None
_chroma: Optional[ChromaDBService] = None


def _get_services():
    global _chunker, _embedder, _chroma
    if _chunker is None:
        _chunker = ChunkingService(chunk_size=512, overlap=128)
    if _embedder is None:
        _embedder = EmbeddingService()
    if _chroma is None:
        _chroma = ChromaDBService()
    return _chunker, _embedder, _chroma


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def embed_document_async(self, document_id: str) -> dict:
    """
    Background task: chunk a document, embed chunks, store in ChromaDB.

    Args:
        document_id: MongoDB ObjectId string of the document to embed.

    Returns:
        Dict with chunk_count and status.
    """
    db = get_sync_db()
    doc = db.documents.find_one({"_id": ObjectId(document_id)})
    if not doc:
        logger.warning("embed_document_async: document %s not found", document_id)
        return {"status": "not_found", "chunk_count": 0}

    text = doc.get("content") or doc.get("abstract") or ""
    if not text.strip():
        logger.info("embed_document_async: document %s has no text, skipping", document_id)
        return {"status": "no_text", "chunk_count": 0}

    try:
        chunker, embedder, chroma = _get_services()

        # 1. Chunk the document
        chunks = chunker.chunk_document(text, document_id=document_id)
        if not chunks:
            return {"status": "no_chunks", "chunk_count": 0}

        # 2. Build metadata for each chunk
        metadatas = []
        for chunk in chunks:
            meta = chunk.to_chromadb_metadata()
            # Carry forward useful document-level fields for filtered searches
            meta["title"] = doc.get("title", "")
            meta["year"] = doc.get("year") or 0
            meta["doi"] = doc.get("doi", "")
            meta["general_domain"] = doc.get("general_domain", "")
            metadatas.append(meta)

        # 3. Batch embed (most efficient — single model pass)
        texts = [c.text for c in chunks]
        embeddings = embedder.embed_batch(texts, show_progress=False)

        # 4. Upsert into ChromaDB
        chroma.add_chunks_batch(
            chunk_ids=[c.chunk_id for c in chunks],
            texts=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        # 5. Persist chunk records to MongoDB (for provenance/ArangoDB later)
        now = datetime.utcnow()
        chunk_docs = [
            {
                "chunk_id": c.chunk_id,
                "document_id": ObjectId(document_id),
                "chunk_index": c.chunk_index,
                "text": c.text,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "embedded": True,
                "created_at": now,
            }
            for c in chunks
        ]
        # Upsert by chunk_id to allow re-embedding
        for cdoc in chunk_docs:
            db.chunks.replace_one(
                {"chunk_id": cdoc["chunk_id"]},
                cdoc,
                upsert=True,
            )

        # 6. Mark document embedding status
        db.documents.update_one(
            {"_id": ObjectId(document_id)},
            {"$set": {"embedding_status": "embedded", "updated_at": now}},
        )

        logger.info(
            "embed_document_async: document %s → %d chunks embedded",
            document_id,
            len(chunks),
        )
        return {"status": "ok", "chunk_count": len(chunks)}

    except Exception as exc:
        logger.exception("embed_document_async failed for %s: %s", document_id, exc)
        raise self.retry(exc=exc)


@celery_app.task
def embed_batch_async(document_ids: list[str]) -> dict:
    """
    Queue embed_document_async for each document ID.
    Returns the number of tasks queued.
    """
    queued = 0
    for doc_id in document_ids:
        embed_document_async.delay(doc_id)
        queued += 1
    logger.info("embed_batch_async: queued %d embedding tasks", queued)
    return {"queued": queued}


@celery_app.task
def re_embed_all(domain_filter: Optional[str] = None) -> dict:
    """
    Re-embed all documents that have text content.
    Used for model upgrades or collection re-indexing.

    Args:
        domain_filter: optional general_domain value to restrict scope.
    """
    db = get_sync_db()
    query: dict = {"content": {"$exists": True, "$ne": ""}}
    if domain_filter:
        query["general_domain"] = domain_filter

    doc_ids = [str(d["_id"]) for d in db.documents.find(query, {"_id": 1})]
    for doc_id in doc_ids:
        embed_document_async.delay(doc_id)

    logger.info("re_embed_all: queued %d documents for re-embedding", len(doc_ids))
    return {"queued": len(doc_ids)}
