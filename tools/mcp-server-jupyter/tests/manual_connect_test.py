import asyncio
import websockets
import json
import argparse
import sys

async def simulate_human_client(uri):
    print(f"Connecting to {uri}...")
    try:
        # MCP uses 'mcp' subprotocol
        async with websockets.connect(uri, subprotocols=['mcp']) as websocket:
            print("✅ Human connected!")
            
            # Send a handshake
            await websocket.send(json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "initialize", 
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}
            }))
            resp = await websocket.recv()
            print(f"✅ Handshake response: {resp}")
            
            # Wait for broadcast
            print("👀 Watching for broadcast...")
            while True:
                msg = await websocket.recv()
                data = json.loads(msg)
                print(f"📩 RECEIVED: {str(data)[:200]}...")
                if data.get("method") == "notebook/output":
                    print(f"✅ RECEIVED BROADCAST: {str(data)[:100]}...")
                    # Don't break immediately, let's keep listening for a bit
    except ConnectionRefusedError:
        print(f"❌ Connection refused. Is the server running? (python -m src.main --transport websocket)")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=3000)
    args = parser.parse_args()
    
    uri = f"ws://localhost:{args.port}/ws"
    
    # Check if websockets is installed
    try:
        import websockets
    except ImportError:
        print("Please install websockets: pip install websockets")
        sys.exit(1)

    print("Run the server first in another terminal: python -m src.main --transport websocket --port 3000 --host 0.0.0.0")
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(simulate_human_client(uri))
