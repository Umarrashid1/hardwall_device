import asyncio
from WebSocketClient import WebSocketClient, receive_backend_commands
from state_manager import StateManager
from usb_monitor import USBMonitor

BACKEND_URI = "ws://130.225.37.50:3000"
MOUNT_POINT = "/mnt/usb"
SERVER_IP = "130.225.37.50"
SSH_PORT = 22
SSH_USERNAME = "ubuntu"
KEY_FILE_PATH = "/home/guest/hardwall_device/cloud.key"
REMOTE_DIR = "/home/ubuntu/box"


async def main():
    state_manager = StateManager()
    ws_client = WebSocketClient(BACKEND_URI)

    # Connect to the backend
    await ws_client.connect(state_manager)

    # Initialize USB monitor
    monitor = USBMonitor(ws_client, state_manager)

    # Start WebSocket command receiver and USB monitor tasks
    command_receiver_task = asyncio.create_task(receive_backend_commands(ws_client, state_manager))
    usb_monitor_task = asyncio.create_task(asyncio.to_thread(monitor.monitor_events))
    inactivity_task = asyncio.create_task(asyncio.to_thread(monitor.monitor_inactivity))

    # Wait for all tasks to complete
    try:
        await asyncio.gather(command_receiver_task, usb_monitor_task, inactivity_task)
    finally:
        await ws_client.close()
        print("WebSocket connection closed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program terminated by user.")
