#!/usr/bin/env python3
"""
Example MCP Gateway Client

This script demonstrates how to connect to the MCP Gateway and interact with
registered agents via the WebSocket protocol.

Requirements:
    pip install websockets

Usage:
    python examples/client.py
"""

import asyncio
import json
import sys
from typing import Any, Dict, Optional

try:
    import websockets
except ImportError:
    print("Error: websockets library not found. Install with: pip install websockets")
    sys.exit(1)


class MCPClient:
    """Simple MCP Gateway client for testing"""
    
    def __init__(self, gateway_url: str = "ws://localhost:8080/mcp"):
        self.gateway_url = gateway_url
        self.websocket = None
        self.request_id = 0
    
    async def connect(self):
        """Connect to the MCP Gateway"""
        print(f"Connecting to {self.gateway_url}...")
        self.websocket = await websockets.connect(self.gateway_url)
        print("Connected!")
    
    async def disconnect(self):
        """Disconnect from the gateway"""
        if self.websocket:
            await self.websocket.close()
            print("Disconnected.")
    
    async def send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a JSON-RPC request and wait for response"""
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {}
        }
        
        print(f"\n→ Sending: {json.dumps(request, indent=2)}")
        await self.websocket.send(json.dumps(request))
        
        response_text = await self.websocket.recv()
        response = json.loads(response_text)
        print(f"← Received: {json.dumps(response, indent=2)}")
        
        return response
    
    async def initialize(self):
        """Initialize the MCP session"""
        return await self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {
                "name": "example-client",
                "version": "1.0.0"
            }
        })
    
    async def list_tools(self) -> Dict[str, Any]:
        """List all available tools"""
        return await self.send_request("tools/list")
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a specific tool"""
        return await self.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
    
    async def run_workflow(self, steps: list) -> Dict[str, Any]:
        """Run a multi-step workflow"""
        return await self.send_request("workflow/run", {
            "steps": steps
        })


async def demo_basic_usage():
    """Demonstrate basic MCP Gateway usage"""
    client = MCPClient()
    
    try:
        # Connect to gateway
        await client.connect()
        
        # Initialize the session
        print("\n=== Initializing Session ===")
        await client.initialize()
        
        # List available tools
        print("\n=== Listing Available Tools ===")
        tools_response = await client.list_tools()
        
        if "result" in tools_response and tools_response["result"]:
            tools = tools_response["result"]
            print(f"\nFound {len(tools)} tools:")
            for tool in tools:
                print(f"  - {tool['name']}: {tool['description']}")
            
            # If there are any tools, try calling the first one
            if tools:
                first_tool = tools[0]
                print(f"\n=== Calling Tool: {first_tool['name']} ===")
                
                # Example arguments (customize based on your agent)
                await client.call_tool(first_tool['name'], {})
        else:
            print("No tools available. Make sure agents are registered!")
            print("\nTo register an agent, use:")
            print("curl -X POST http://localhost:8080/agents \\")
            print("  -H 'Content-Type: application/json' \\")
            print("  -d '{")
            print('    "name": "example-agent",')
            print('    "websocket_url": "ws://localhost:9001",')
            print('    "tools": [{"name": "example_tool", "description": "Example", "inputSchema": {}}]')
            print("  }'")
        
    except websockets.exceptions.WebSocketException as e:
        print(f"\nWebSocket error: {e}")
        print("Make sure the MCP Gateway is running on localhost:8080")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        await client.disconnect()


async def demo_workflow():
    """Demonstrate workflow execution"""
    client = MCPClient()
    
    try:
        await client.connect()
        await client.initialize()
        
        print("\n=== Running Workflow ===")
        workflow_steps = [
            {
                "tool": "step1_tool",
                "arguments": {"input": "data"}
            },
            {
                "tool": "step2_tool",
                "arguments": {"data": "{{step0.result}}"}
            }
        ]
        
        await client.run_workflow(workflow_steps)
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await client.disconnect()


def main():
    """Main entry point"""
    print("MCP Gateway Example Client")
    print("===========================\n")
    
    if len(sys.argv) > 1 and sys.argv[1] == "workflow":
        asyncio.run(demo_workflow())
    else:
        asyncio.run(demo_basic_usage())


if __name__ == "__main__":
    main()
