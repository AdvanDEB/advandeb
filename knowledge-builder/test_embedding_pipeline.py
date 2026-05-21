#!/usr/bin/env python3
"""
Quick embedding test — embed a few sample documents from ArangoDB to ChromaDB.

This is a simplified version of the batch ingestion pipeline for testing.
Runs synchronously (no Celery).
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _get_arango_db():
    from advandeb_kb.database.arango_client import ArangoDatabase
    from advandeb_kb.config.settings import settings as kb_settings

    client = ArangoDatabase(
        url=kb_settings.ARANGO_URL,
        db_name=kb_settings.ARANGO_DB_NAME,
        username=kb_settings.ARANGO_USERNAME,
        password=kb_settings.ARANGO_PASSWORD,
    )
    client.connect()
    return client.db


async def embed_sample_documents(limit: int = 10):
    """Embed a few sample documents for testing."""
    print(f"Embedding {limit} sample documents...\n")

    try:
        from advandeb_kb.services.embedding_service import EmbeddingService
        from advandeb_kb.services.chromadb_service import ChromaDBService
        from advandeb_kb.services.chunking_service import ChunkingService

        db = _get_arango_db()

        print("Loading embedding model...")
        embedding_svc = EmbeddingService()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, embedding_svc._load)

        print("Connecting to ChromaDB...")
        chroma_svc = ChromaDBService()
        chroma_svc._ensure_connected()

        print("Initializing chunking service...\n")
        chunking_svc = ChunkingService(chunk_size=512, overlap=128)

        # Fetch documents with content that are not yet embedded
        cursor = db.aql.execute(
            """
            FOR doc IN documents
                FILTER doc.content != null AND doc.content != ""
                   AND doc.embedding_status != "completed"
                LIMIT @limit
                RETURN { _key: doc._key, title: doc.title, content: doc.content }
            """,
            bind_vars={"limit": limit},
        )
        docs = list(cursor)

        if not docs:
            print("No documents with content found (or all already embedded)")
            print("   Run batch_ingest.py first to extract PDF text")
            return 0

        print(f"Found {len(docs)} documents to embed\n")

        total_chunks = 0

        for i, doc in enumerate(docs, 1):
            doc_id = doc["_key"]
            title  = doc.get("title", "Untitled")
            content = doc["content"]

            print(f"[{i}/{len(docs)}] Processing: {title[:60]}...")

            chunks = chunking_svc.chunk_document(content, doc_id)
            print(f"   -> {len(chunks)} chunks created")

            for chunk in chunks:
                embedding = await loop.run_in_executor(
                    None,
                    embedding_svc.embed_text,
                    chunk.text,
                )
                chroma_svc.add_chunk(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    embedding=embedding,
                    metadata=chunk.to_chromadb_metadata(),
                )

            total_chunks += len(chunks)

            # Mark document as embedded in ArangoDB
            db.collection("documents").update(
                {"_key": doc_id},
                {"embedding_status": "completed", "num_chunks": len(chunks)},
            )

            print(f"   Embedded and stored {len(chunks)} chunks")

        print(f"\n{'='*60}")
        print(f"Successfully embedded {len(docs)} documents")
        print(f"   Total chunks:    {total_chunks}")
        print(f"   ChromaDB total:  {chroma_svc.count()} chunks")
        print(f"{'='*60}")
        return len(docs)

    except Exception as e:
        print(f"Embedding failed: {e}")
        import traceback
        traceback.print_exc()
        return 0


async def test_retrieval():
    """Test retrieval after embedding."""
    print("\nTesting retrieval with embedded documents...\n")

    try:
        from advandeb_kb.services.embedding_service import EmbeddingService
        from advandeb_kb.services.chromadb_service import ChromaDBService
        from advandeb_kb.services.hybrid_retrieval_service import HybridRetrievalService

        embedding_svc = EmbeddingService()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, embedding_svc._load)

        chroma_svc = ChromaDBService()
        chroma_svc._ensure_connected()

        hybrid_svc = HybridRetrievalService(
            embedding_svc=embedding_svc,
            chromadb_svc=chroma_svc,
        )

        query = "Dynamic Energy Budget theory for fish"
        print(f"Query: '{query}'")
        print(f"Searching {chroma_svc.count()} chunks...\n")

        results = await hybrid_svc.retrieve(query, top_k=5)

        print(f"Retrieved {len(results)} results:\n")
        for i, result in enumerate(results, 1):
            chunk_text = result.text[:150]
            score = result.rrf_score
            print(f"[{i}] RRF Score: {score:.4f}")
            print(f"    {chunk_text}...")
            print(f"    (doc: {result.metadata.get('document_id', 'unknown')})\n")

        return True

    except Exception as e:
        print(f"Retrieval test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run embedding and retrieval test."""
    print("=" * 60)
    print("AdvanDEB Knowledge Builder - Embedding Pipeline Test")
    print("=" * 60)
    print()

    num_embedded = await embed_sample_documents(limit=5)

    if num_embedded > 0:
        await test_retrieval()

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
