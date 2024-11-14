import asyncio
import websockets
import subprocess  # For running system commands

async def connect_to_backend():
    uri = "ws://130.225.37.50:3000"
    async with websockets.connect(uri) as websocket:
        print("Connected to backend")

        # Receive commands from the backend
        while True:
            message = await websocket.recv()
            print(f"Received message: {message}")
            
            if message == "Start scan":
                # Trigger USB proxy or start the scan process
                start_scan_process()
                await websocket.send("Scan started")

            elif message == "Stop scan":
                # Handle stopping the scan process
                stop_scan_process()
                await websocket.send("Scan stopped")

def start_scan_process():
    print("Starting USB device scan...")
    # Example: Run a system command to start USB proxying or scanning
    # Replace with actual commands or functions to interact with USB devices
    subprocess.run(["usbproxy", "start"])

def stop_scan_process():
    print("Stopping scan...")
    # Example: Run a system command to stop scanning or interaction
    subprocess.run(["usbproxy", "stop"])

# Run the WebSocket client
asyncio.get_event_loop().run_until_complete(connect_to_backend())

