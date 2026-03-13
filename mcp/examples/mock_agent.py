#!/usr/bin/env python3
"""
Mock MCP Agent

A simple example agent that can be registered with the MCP Gateway.
This agent provides basic tools for testing purposes.

Requirements:
    pip install websockets

Usage:
    python examples/mock_agent.py [--port 9001]
"""

import asyncio
import json
import argparse
from typing import Dict, Any

try:
    import websockets
    from websockets.server import serve
except ImportError:
    print("Error: websockets library not found. Install with: pip install websockets")
    import sys
    sys.exit(1)


class MockAgent:
    """A simple mock agent for testing"""
    
    def __init__(self, name: str = "mock-agent", port: int = 9001):
        self.name = name
        self.port = port
        self.tools = {
            "echo": {
                "name": "echo",
                "description": "Echo back the input message",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"}
                    },
                    "required": ["message"]
                }
            },
            "calculator": {
                "name": "calculator",
                "description": "Perform basic arithmetic operations",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["add", "subtract", "multiply", "divide"]},
                        "a": {"type": "number"},
                        "b": {"type": "number"}
                    },
                    "required": ["operation", "a", "b"]
                }
            },
            "random": {
                "name": "random",
                "description": "Generate a random number between min and max",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "min": {"type": "number", "default": 0},
                        "max": {"type": "number", "default": 100}
                    }
                }
            }
        }
    
    def handle_echo(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Echo tool handler"""
        message = arguments.get("message", "")
        return {"echo": message, "length": len(message)}
    
    def handle_calculator(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Calculator tool handler"""
        operation = arguments.get("operation")
        a = arguments.get("a", 0)
        b = arguments.get("b", 0)
        
        operations = {
            "add": lambda x, y: x + y,
            "subtract": lambda x, y: x - y,
            "multiply": lambda x, y: x * y,
            "divide": lambda x, y: x / y if y != 0 else None
        }
        
        if operation not in operations:
            raise ValueError(f"Unknown operation: {operation}")
        
        result = operations[operation](a, b)
        if result is None:
            raise ValueError("Division by zero")
        
        return {"result": result, "operation": operation, "a": a, "b": b}
    
    def handle_random(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Random number generator tool handler"""
        import random
        min_val = arguments.get("min", 0)
        max_val = arguments.get("max", 100)
        value = random.uniform(min_val, max_val)
        return {"value": value, "min": min_val, "max": max_val}
    
    async def handle_connection(self, websocket, path):
        """Handle incoming WebSocket connection"""
        print(f"New connection from {websocket.remote_address}")
        
        try:
            async for message in websocket:
                try:
                    request = json.loads(message)
                    print(f"← Received: {json.dumps(request, indent=2)}")
                    
                    response = await self.handle_request(request)
                    
                    print(f"→ Sending: {json.dumps(response, indent=2)}")
                    await websocket.send(json.dumps(response))
                    
                except json.JSONDecodeError as e:
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32700,
                            "message": f"Parse error: {str(e)}"
                        }
                    }
                    await websocket.send(json.dumps(error_response))
                except Exception as e:
                    print(f"Error handling request: {e}")
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "error": {
                            "code": -32603,
                            "message": f"Internal error: {str(e)}"
                        }
                    }
                    await websocket.send(json.dumps(error_response))
        except websockets.exceptions.ConnectionClosed:
            print(f"Connection closed from {websocket.remote_address}")
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a JSON-RPC request"""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")
        
        # Handle MCP protocol methods
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": self.name,
                        "version": "1.0.0"
                    }
                }
            }
        
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": list(self.tools.values())
            }
        
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            if tool_name not in self.tools:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Tool not found: {tool_name}"
                    }
                }
            
            try:
                # Route to appropriate handler
                handlers = {
                    "echo": self.handle_echo,
                    "calculator": self.handle_calculator,
                    "random": self.handle_random
                }
                
                result = handlers[tool_name](arguments)
                
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": f"Tool execution failed: {str(e)}"
                    }
                }
        
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }
    
    async def start(self):
        """Start the agent server"""
        print(f"Starting {self.name} on ws://0.0.0.0:{self.port}")
        print(f"Available tools: {', '.join(self.tools.keys())}")
        print("\nTo register with the gateway, run:")
        print(f'curl -X POST http://localhost:8080/agents \\')
        print(f'  -H "Content-Type: application/json" \\')
        print(f"  -d '{{")
        print(f'    "name": "{self.name}",')
        print(f'    "websocket_url": "ws://localhost:{self.port}",')
        print(f'    "tools": {json.dumps(list(self.tools.values()), indent=6)}')
        print(f"  }}'\n")
        
        async with serve(self.handle_connection, "0.0.0.0", self.port):
            await asyncio.Future()  # Run forever


def main():
    parser = argparse.ArgumentParser(description="Mock MCP Agent for testing")
    parser.add_argument("--port", type=int, default=9001, help="Port to listen on")
    parser.add_argument("--name", type=str, default="mock-agent", help="Agent name")
    args = parser.parse_args()
    
    agent = MockAgent(name=args.name, port=args.port)
    
    try:
        asyncio.run(agent.start())
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
