#!/usr/bin/env python3
"""
Test the KG Builder service (document-taxon linking).
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

async def test_mongodb_connection():
    """Test MongoDB connection and check data availability."""
    print("🧪 Testing MongoDB connection...")
    try:
        from advandeb_kb.database.mongodb import mongodb
        
        await mongodb.connect()
        
        # Check collections
        doc_count = await mongodb.database.documents.count_documents({})
        taxa_count = await mongodb.database.taxonomy_nodes.count_documents({})
        facts_count = await mongodb.database.facts.count_documents({})
        sf_count = await mongodb.database.stylized_facts.count_documents({})
        
        print(f"✅ MongoDB connected successfully")
        print(f"   Documents: {doc_count}")
        print(f"   Taxonomy nodes: {taxa_count}")
        print(f"   Facts: {facts_count}")
        print(f"   Stylized facts: {sf_count}")
        
        await mongodb.disconnect()
        return True
        
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return False

async def test_kg_builder_service():
    """Test KG Builder service initialization."""
    print("\n🧪 Testing KG Builder Service...")
    try:
        from advandeb_kb.database.mongodb import mongodb
        from advandeb_kb.services.kg_builder_service import KGBuilderService
        
        await mongodb.connect()
        db = mongodb.database
        
        # Create service
        service = KGBuilderService(db)
        
        # Check if we have taxonomy data
        taxa_count = await db.taxonomy_nodes.count_documents({})
        if taxa_count == 0:
            print("⚠️  No taxonomy data available - skipping index build")
            print("   (This is OK - run OpenAlex import or taxonomy ingestion first)")
            await mongodb.disconnect()
            return True
        
        # Build name index (mammals subtree as example)
        print(f"   Building name index from {taxa_count} taxonomy nodes...")
        # Use a common test root_taxid: 40674 = Mammalia
        index_size = await service.build_name_index(root_taxid=40674)
        
        print(f"✅ KG Builder service initialized")
        print(f"   Index size: {index_size} name entries")
        print(f"   Index ready: {service.index_ready()}")
        
        await mongodb.disconnect()
        return True
        
    except Exception as e:
        print(f"❌ KG Builder service test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_chromadb_status():
    """Test ChromaDB embedded instance."""
    print("\n🧪 Testing ChromaDB...")
    try:
        from advandeb_kb.services.chromadb_service import ChromaDBService
        
        chroma = ChromaDBService()
        chroma._ensure_connected()
        
        count = chroma.count()
        print(f"✅ ChromaDB connected (embedded mode)")
        print(f"   Chunks stored: {count}")
        
        return True
        
    except Exception as e:
        print(f"❌ ChromaDB test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_embedding_service():
    """Test embedding service (model loading)."""
    print("\n🧪 Testing Embedding Service...")
    try:
        from advandeb_kb.services.embedding_service import EmbeddingService
        
        service = EmbeddingService()
        # Load model in thread pool (blocking operation)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, service._load)
        
        # Test embedding
        test_text = "Dynamic Energy Budget theory for fish growth"
        embedding = service.embed_text(test_text)
        
        print(f"✅ Embedding service working")
        print(f"   Model: {service.model_name}")
        print(f"   Embedding dimension: {len(embedding)}")
        print(f"   Sample values: [{embedding[0]:.4f}, {embedding[1]:.4f}, ...]")
        
        return True
        
    except Exception as e:
        print(f"❌ Embedding service test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_hybrid_retrieval():
    """Test hybrid retrieval service."""
    print("\n🧪 Testing Hybrid Retrieval Service...")
    try:
        from advandeb_kb.services.embedding_service import EmbeddingService
        from advandeb_kb.services.chromadb_service import ChromaDBService
        from advandeb_kb.services.hybrid_retrieval_service import HybridRetrievalService
        
        # Initialize services
        embedding_svc = EmbeddingService()
        chroma_svc = ChromaDBService()
        chroma_svc._ensure_connected()
        
        hybrid_svc = HybridRetrievalService(
            embedding_svc=embedding_svc,
            chromadb_svc=chroma_svc
        )
        
        print(f"✅ Hybrid retrieval service initialized")
        
        # Only test actual retrieval if we have chunks
        chunk_count = chroma_svc.count()
        if chunk_count > 0:
            print(f"   Testing retrieval with {chunk_count} chunks...")
            results = await hybrid_svc.retrieve("DEB theory", top_k=3)
            print(f"   Retrieved {len(results)} results")
        else:
            print("   (No chunks in database yet - skipping retrieval test)")
        
        return True
        
    except Exception as e:
        print(f"❌ Hybrid retrieval test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all tests."""
    print("=" * 60)
    print("AdvanDEB Knowledge Builder - Service Tests")
    print("=" * 60)
    
    results = []
    
    # Test 1: MongoDB
    results.append(await test_mongodb_connection())
    
    # Test 2: ChromaDB
    results.append(await test_chromadb_status())
    
    # Test 3: Embedding Service
    results.append(await test_embedding_service())
    
    # Test 4: KG Builder Service
    results.append(await test_kg_builder_service())
    
    # Test 5: Hybrid Retrieval
    results.append(await test_hybrid_retrieval())
    
    # Summary
    print("\n" + "=" * 60)
    print(f"Test Results: {sum(results)}/{len(results)} passed")
    print("=" * 60)
    
    if all(results):
        print("✅ All service tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed. Check errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
