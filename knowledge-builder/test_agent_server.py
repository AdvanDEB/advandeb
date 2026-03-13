#!/usr/bin/env python3
"""
Test starting an agent and connecting to it via MCP client.
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

async def test_agent_server():
    """Start RetrievalAgent and test MCP communication."""
    print("=" * 60)
    print("Agent Server Test - RetrievalAgent on port 8081")
    print("=" * 60)
    print()
    
    # Import agent
    from advandeb_kb.agents.retrieval_agent import RetrievalAgent
    from advandeb_kb.mcp.protocol import MCPClient
    
    # Create agent
    print("🚀 Starting RetrievalAgent...")
    agent = RetrievalAgent(port=8081, host="localhost")
    
    # Initialize and register tools
    await agent.initialize()
    agent.register_tools()
    print(f"✅ Agent initialized: {len(agent.server._tools)} tools registered")
    
    # Start server (this will run forever, so we do it in a task)
    print("🌐 Starting WebSocket server on ws://localhost:8081...")
    server_task = asyncio.create_task(agent.server.start())
    
    # Wait a moment for server to start
    await asyncio.sleep(1)
    
    # Test with client
    print("\n🧪 Testing client connection...\n")
    client = MCPClient("ws://localhost:8081")
    
    try:
        # Test 1: Ping
        print("[1/4] Ping test...")
        pong = await asyncio.wait_for(client.ping(), timeout=5.0)
        print(f"   ✅ Ping successful: {pong}")
        
        # Test 2: List tools
        print("[2/4] Listing tools...")
        tools = await asyncio.wait_for(client.list_tools(), timeout=5.0)
        print(f"   ✅ Found {len(tools)} tools:")
        for tool in tools:
            print(f"      - {tool['name']}: {tool['description'][:60]}...")
        
        # Test 3: Embed query
        print("[3/4] Testing embed_query tool...")
        result = await asyncio.wait_for(
            client.call_tool(
                tool_name="embed_query",
                arguments={"text": "Dynamic Energy Budget theory"}
            ),
            timeout=10.0
        )
        embedding = result.get("embedding", [])
        print(f"   ✅ Generated embedding: dimension={len(embedding)}")
        print(f"      Sample values: [{embedding[0]:.4f}, {embedding[1]:.4f}, ...]")
        
        # Test 4: Semantic search
        print("[4/4] Testing semantic_search tool...")
        result = await asyncio.wait_for(
            client.call_tool(
                tool_name="semantic_search",
                arguments={
                    "query": "fish reproduction and spawning",
                    "top_k": 3
                }
            ),
            timeout=10.0
        )
        chunks = result.get("chunks", [])
        print(f"   ✅ Retrieved {len(chunks)} chunks")
        if chunks:
            for i, chunk in enumerate(chunks, 1):
                print(f"      [{i}] {chunk.get('text', '')[:80]}...")
        
        print("\n" + "=" * 60)
        print("✅ All tests passed! Agent is working correctly.")
        print("=" * 60)
        
    except asyncio.TimeoutError:
        print("❌ Timeout - agent not responding")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Stop server
        print("\n🛑 Stopping server...")
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
    
    return True

if __name__ == "__main__":
    result = asyncio.run(test_agent_server())
    sys.exit(0 if result else 1)
