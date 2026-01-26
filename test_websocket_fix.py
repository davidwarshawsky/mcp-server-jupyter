#!/usr/bin/env python3
"""Test WebSocket connection to MCP server

Note: Manual script. Automated WebSocket tests exist (see test_mcp_websocket_subprotocol.py
and test_websocket_transport.py). Mark skipped for pytest.
"""
import pytest
pytestmark = pytest.mark.skip("Manual script, covered by automated tests.")
import asyncio
import json
import websockets

async def test_connection():
    uri = "ws://127.0.0.1:3000/ws"
    print(f"Attempting to connect to {uri}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ WebSocket connection successful!")
            
            # Try to send an initialize request
            init_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "test-client",
                        "version": "0.1.0"
                    }
                }
            }
            
            print(f"Sending initialize request...")
            await websocket.send(json.dumps(init_request))
            
            print("Waiting for response...")
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            print(f"✅ Received response: {response[:100]}...")
            
            response_data = json.loads(response)
            if "result" in response_data:
                print("✅ Server initialized successfully!")
                return True
            else:
                print(f"❌ Unexpected response: {response_data}")
                return False
            
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"❌ Invalid status code: {e.status_code}")
        print(f"   This means the server rejected the WebSocket upgrade")
        return False
    except Exception as e:
        print(f"❌ Connection failed: {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_connection())
    exit(0 if result else 1)
