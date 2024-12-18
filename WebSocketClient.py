import asyncio
import websockets
import json

HEADERS = {"x-device-type": "Pi"}

class WebSocketClient:
    """Manages a WebSocket connection to a server with reconnection logic."""
    def __init__(self, server_url):
        self.server_url = server_url
        self.ws = None
        self.lock = asyncio.Lock()  # Prevent concurrent reconnections
        self.reconnect_delay = 5    # Fixed delay between reconnect attempts
        self.reconnecting = False   # Flag to prevent multiple reconnects

    async def connect(self, state_manager=None):
        """Attempt to establish a connection to the WebSocket server."""
        async with self.lock:  # Prevent concurrent connection attempts
            while not self.ws:
                try:
                    print(f"Connecting to WebSocket server at {self.server_url}...")
                    self.ws = await asyncio.wait_for(
                        websockets.connect(self.server_url, extra_headers=HEADERS), timeout=10
                    )
                    print("Connected to WebSocket server.")
                    if state_manager:
                        await state_manager.set_status("block", ws_client=self)
                    return  # Exit after successful connection
                except (asyncio.TimeoutError, Exception) as e:
                    print(f"Connection failed: {e}. Retrying in {self.reconnect_delay} seconds...")
                    await asyncio.sleep(self.reconnect_delay)
                except Exception as e:
                    print(f"Unexpected error during connection: {e}")
                    await asyncio.sleep(self.reconnect_delay)

    async def reconnect(self, state_manager=None):
        """Centralized reconnection logic with delay."""
        if self.reconnecting:
            print("Reconnection already in progress. Skipping duplicate attempt.")
            return

        self.reconnecting = True
        self.ws = None  # Reset the WebSocket connection object

        while self.ws is None or self.ws.closed:
            print(f"Reconnecting to WebSocket server in {self.reconnect_delay} seconds...")
            await asyncio.sleep(self.reconnect_delay)

            try:
                await self.connect(state_manager)  # Attempt reconnection
            except Exception as e:
                print(f"Reconnection attempt failed: {e}")
        self.reconnecting = False

    async def send_message(self, message):
        """Send a message to the WebSocket server."""
        try:
            if self.ws and not self.ws.closed:
                await self.ws.send(json.dumps(message))
                print(f"Sent message: {message}")
            else:
                print("WebSocket is closed. Triggering reconnect...")
                await self.reconnect()
        except websockets.ConnectionClosed:
            print("Connection closed while sending. Triggering reconnect...")
            await self.reconnect()

    async def close(self):
        """Close the WebSocket connection."""
        if self.ws:
            await self.ws.close()
            print("WebSocket connection closed.")
            self.ws = None

async def receive_backend_commands(ws_client, state_manager):
    """Continuously receive and handle commands from the backend."""
    while True:
        try:
            # Wait for WebSocket messages
            if ws_client.ws and not ws_client.ws.closed:
                message = await ws_client.ws.recv()
                print(f"Received message from backend: {message}")
                command = json.loads(message)
                action = command.get("action")
                device_info = command.get("device_info")

                # Handle the "allow" and "block" actions
                if action == "allow":
                    await state_manager.set_status("allow", device_info, ws_client)
                elif action == "block":
                    await state_manager.set_status("block", ws_client=ws_client)

            else:
                # If WebSocket is closed, trigger reconnect
                print("WebSocket connection lost. Reconnecting...")
                await ws_client.reconnect(state_manager)

        except websockets.ConnectionClosed:
            print("Connection closed while receiving. Triggering reconnect...")
            await ws_client.reconnect(state_manager)

        except Exception as e:
            print(f"Error while receiving commands: {e}")
            await asyncio.sleep(5)  # Wait before retrying
