#!/usr/bin/env python3
"""
Quick smoke test for agent system.
Tests if agents can be imported and initialized (without starting WebSocket servers).
"""
import sys
import asyncio
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

async def test_imports():
    """Test that all agents can be imported."""
    print("🧪 Testing agent imports...")
    try:
        from advandeb_kb.agents.retrieval_agent import RetrievalAgent
        from advandeb_kb.agents.graph_explorer_agent import GraphExplorerAgent
        from advandeb_kb.agents.synthesis_agent import SynthesisAgent
        from advandeb_kb.agents.query_planner_agent import QueryPlannerAgent
        from advandeb_kb.agents.curator_agent import CuratorAgent
        print("✅ All agents imported successfully")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False

async def test_retrieval_agent_init():
    """Test RetrievalAgent can initialize (loads model + connects to ChromaDB)."""
    print("\n🧪 Testing RetrievalAgent initialization...")
    try:
        from advandeb_kb.agents.retrieval_agent import RetrievalAgent
        
        # Create agent (don't start server)
        agent = RetrievalAgent(port=8081, host="localhost")
        
        # Initialize (loads embedding model, connects to ChromaDB)
        await agent.initialize()
        
        # Register tools (should work without starting server)
        agent.register_tools()
        
        # Check tools registered
        tools = agent.server._tools
        expected_tools = {"semantic_search", "hybrid_search", "find_similar_chunks", "embed_query"}
        if set(tools.keys()) == expected_tools:
            print(f"✅ RetrievalAgent initialized with {len(tools)} tools: {list(tools.keys())}")
            return True
        else:
            print(f"⚠️  Expected tools {expected_tools}, got {set(tools.keys())}")
            return False
            
    except Exception as e:
        print(f"❌ RetrievalAgent initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_mcp_protocol():
    """Test MCP protocol classes are available."""
    print("\n🧪 Testing MCP protocol...")
    try:
        from advandeb_kb.mcp.protocol import MCPServer, MCPClient
        
        # Create a test server (don't start)
        server = MCPServer(port=9999, host="localhost")
        
        # Register a simple tool
        async def test_tool(message: str) -> dict:
            return {"echo": message}
        
        server.register_tool(
            name="test_echo",
            handler=test_tool,
            description="Test echo tool",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"}
                },
                "required": ["message"]
            }
        )
        
        if "test_echo" in server._tools:
            print("✅ MCP protocol working")
            return True
        else:
            print("❌ Tool registration failed")
            return False
            
    except Exception as e:
        print(f"❌ MCP protocol test failed: {e}")
        return False

async def test_services():
    """Test that key services can be imported and created."""
    print("\n🧪 Testing services...")
    try:
        from advandeb_kb.services.embedding_service import EmbeddingService
        from advandeb_kb.services.chromadb_service import ChromaDBService
        from advandeb_kb.services.hybrid_retrieval_service import HybridRetrievalService
        
        # Test embedding service (don't load model yet)
        embedding_svc = EmbeddingService()
        
        # Test ChromaDB service
        chroma_svc = ChromaDBService()
        
        # Test hybrid retrieval service
        hybrid_svc = HybridRetrievalService(
            embedding_svc=embedding_svc,
            chromadb_svc=chroma_svc
        )
        
        print("✅ All services can be instantiated")
        return True
        
    except Exception as e:
        print(f"❌ Service test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all tests."""
    print("=" * 60)
    print("AdvanDEB Knowledge Builder - Agent System Smoke Test")
    print("=" * 60)
    
    results = []
    
    # Test 1: Imports
    results.append(await test_imports())
    
    # Test 2: MCP Protocol
    results.append(await test_mcp_protocol())
    
    # Test 3: Services
    results.append(await test_services())
    
    # Test 4: RetrievalAgent (most complex, requires model loading)
    # This one may take a minute due to model download
    results.append(await test_retrieval_agent_init())
    
    # Summary
    print("\n" + "=" * 60)
    print(f"Test Results: {sum(results)}/{len(results)} passed")
    print("=" * 60)
    
    if all(results):
        print("✅ All tests passed! Agent system is ready.")
        return 0
    else:
        print("⚠️  Some tests failed. Check errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
