#!/usr/bin/env python3
"""
Test the KG Builder service (document-taxon linking) — ArangoDB edition.
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_arango_connection():
    """Test ArangoDB connection and check data availability."""
    print("Testing ArangoDB connection...")
    try:
        from advandeb_kb.database.arango_client import ArangoDatabase
        from advandeb_kb.config.settings import settings as kb_settings

        client = ArangoDatabase(
            url=kb_settings.ARANGO_URL,
            db_name=kb_settings.ARANGO_DB_NAME,
            username=kb_settings.ARANGO_USERNAME,
            password=kb_settings.ARANGO_PASSWORD,
        )
        client.connect()
        db = client.db

        doc_count  = db.collection("documents").count()
        taxa_count = db.collection("taxa").count()
        facts_count = db.collection("facts").count()
        sf_count   = db.collection("stylized_facts").count()

        print("ArangoDB connected successfully")
        print(f"   Documents:      {doc_count}")
        print(f"   Taxa:           {taxa_count}")
        print(f"   Facts:          {facts_count}")
        print(f"   Stylized facts: {sf_count}")
        return True

    except Exception as e:
        print(f"ArangoDB connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_kg_builder_service():
    """Test KG Builder service initialization."""
    print("\nTesting KG Builder Service...")
    try:
        from advandeb_kb.database.arango_client import ArangoDatabase
        from advandeb_kb.config.settings import settings as kb_settings
        from advandeb_kb.services.kg_builder_service import KGBuilderService

        client = ArangoDatabase(
            url=kb_settings.ARANGO_URL,
            db_name=kb_settings.ARANGO_DB_NAME,
            username=kb_settings.ARANGO_USERNAME,
            password=kb_settings.ARANGO_PASSWORD,
        )
        client.connect()

        service = KGBuilderService(client.db)

        taxa_count = client.db.collection("taxa").count()
        if taxa_count == 0:
            print("No taxonomy data available — skipping index build")
            print("   (Run taxonomy ingestion first)")
            return True

        print(f"   Building name index from {taxa_count} taxa...")
        index_size = service.build_name_index(root_taxid=40674)  # Mammalia

        print("KG Builder service initialized")
        print(f"   Index size:  {index_size} name entries")
        print(f"   Index ready: {service.index_ready()}")
        return True

    except Exception as e:
        print(f"KG Builder service test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_chromadb_status():
    """Test ChromaDB embedded instance."""
    print("\nTesting ChromaDB...")
    try:
        from advandeb_kb.services.chromadb_service import ChromaDBService

        chroma = ChromaDBService()
        chroma._ensure_connected()

        count = chroma.count()
        print("ChromaDB connected (embedded mode)")
        print(f"   Chunks stored: {count}")
        return True

    except Exception as e:
        print(f"ChromaDB test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_embedding_service():
    """Test embedding service (model loading)."""
    print("\nTesting Embedding Service...")
    try:
        from advandeb_kb.services.embedding_service import EmbeddingService

        service = EmbeddingService()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, service._load)

        test_text = "Dynamic Energy Budget theory for fish growth"
        embedding = service.embed_text(test_text)

        print("Embedding service working")
        print(f"   Model:      {service.model_name}")
        print(f"   Dimension:  {len(embedding)}")
        print(f"   Sample:     [{embedding[0]:.4f}, {embedding[1]:.4f}, ...]")
        return True

    except Exception as e:
        print(f"Embedding service test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_hybrid_retrieval():
    """Test hybrid retrieval service."""
    print("\nTesting Hybrid Retrieval Service...")
    try:
        from advandeb_kb.services.embedding_service import EmbeddingService
        from advandeb_kb.services.chromadb_service import ChromaDBService
        from advandeb_kb.services.hybrid_retrieval_service import HybridRetrievalService

        embedding_svc = EmbeddingService()
        chroma_svc = ChromaDBService()
        chroma_svc._ensure_connected()

        hybrid_svc = HybridRetrievalService(
            embedding_svc=embedding_svc,
            chromadb_svc=chroma_svc,
        )

        print("Hybrid retrieval service initialized")

        chunk_count = chroma_svc.count()
        if chunk_count > 0:
            print(f"   Testing retrieval with {chunk_count} chunks...")
            results = await hybrid_svc.retrieve("DEB theory", top_k=3)
            print(f"   Retrieved {len(results)} results")
        else:
            print("   (No chunks in database yet — skipping retrieval test)")

        return True

    except Exception as e:
        print(f"Hybrid retrieval test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("AdvanDEB Knowledge Builder - Service Tests")
    print("=" * 60)

    results = []
    results.append(test_arango_connection())
    results.append(await test_chromadb_status())
    results.append(await test_embedding_service())
    results.append(test_kg_builder_service())
    results.append(await test_hybrid_retrieval())

    print("\n" + "=" * 60)
    print(f"Test Results: {sum(results)}/{len(results)} passed")
    print("=" * 60)

    if all(results):
        print("All service tests passed!")
        return 0
    else:
        print("Some tests failed. Check errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
