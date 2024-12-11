import os
import subprocess
import pyudev
import asyncio
import websockets
import json
import paramiko
import time
from scp import SCPClient

BACKEND_URI = "ws://130.225.37.50:3000"
HEADERS = {"x-device-type": "Pi"}
MOUNT_POINT = "/mnt/usb"
SERVER_IP = "130.225.37.50"
SSH_PORT = 22
SSH_USERNAME = "ubuntu"
KEY_FILE_PATH = "/home/guest/hardwall_device/cloud.key"
REMOTE_DIR = "/home/ubuntu/box"


def get_device_info(device):
    """Get USB device information."""
    device_id = f"{device.get('ID_VENDOR_ID')}:{device.get('ID_MODEL_ID')}"
    print(f"Detected device with ID: {device_id}")
    try:
        result = subprocess.run(['lsusb', '-v', '-d', device_id], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0 and "Mass Storage" in result.stdout.decode():
            print("Device is a USB Mass Storage device.")
            return {"type": "deviceInfo", "lsusb_output": result.stdout.decode()}
    except Exception as e:
        print(f"Error accessing device info: {e}")
    return None


def get_block_device_from_device_node(device_node):
    """Find and return the block device associated with the given USB device node."""
    context = pyudev.Context()
    try:
        device = pyudev.Devices.from_device_file(context, device_node)
        print(f"Looking for block device related to: {device_node}")
        for _ in range(10):
            for dev in context.list_devices(subsystem='block'):
                if device in dev.ancestors:
                    print(f"Found block device: {dev.device_node}")
                    return dev.device_node
            time.sleep(0.5)
    except Exception as e:
        print(f"Error finding block device: {e}")
    print("No block device found.")
    return None


def mount_usb_device(device_node):
    """Mount the USB device."""
    os.makedirs(MOUNT_POINT, exist_ok=True)
    try:
        block_device = get_block_device_from_device_node(device_node)
        if not block_device:
            return None

        # Check for partitions
        partition = None
        for part in os.listdir('/dev'):
            if part.startswith(os.path.basename(block_device)) and part != os.path.basename(block_device):
                partition = f"/dev/{part}"
                break
        partition = partition or block_device

        subprocess.run(["sudo", "mount", partition, MOUNT_POINT], check=True)
        print(f"Mounted {partition} at {MOUNT_POINT}")
        return MOUNT_POINT
    except subprocess.CalledProcessError as e:
        print(f"Failed to mount device: {e}")
        return None


def gather_files(mount_point):
    """Collect all files in the mounted directory."""
    files = []
    for root, _, filenames in os.walk(mount_point):
        for filename in filenames:
            files.append(os.path.join(root, filename))
    return files


def transfer_files(file_list):
    """Transfer files to the remote server via SCP."""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(SERVER_IP, port=SSH_PORT, username=SSH_USERNAME, key_filename=KEY_FILE_PATH)
        print(f"Connected to {SERVER_IP} via SSH.")
        with SCPClient(ssh.get_transport()) as scp:
            for file in file_list:
                scp.put(file, REMOTE_DIR)
                print(f"Transferred {file} to {REMOTE_DIR}")
        ssh.close()
    except Exception as e:
        print(f"Error transferring files: {e}")


def unmount_device(mount_point):
    """Unmount the USB device."""
    try:
        subprocess.run(["sudo", "umount", mount_point], check=True)
        print(f"Unmounted {mount_point}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to unmount {mount_point}: {e}")


async def monitor_usb_devices(websocket):
    """Monitor USB devices asynchronously and send info to the backend."""
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by('usb')

    print("Monitoring USB devices...")

    def sync_monitor():
        """Synchronous USB monitoring to be run in a separate thread."""
        for device in iter(monitor.poll, None):
            if device.action == 'add' and 'DEVNAME' in device:
                return device  # Return the device when added

    while True:
        # Run the blocking monitor in a thread and await the result
        device = await asyncio.to_thread(sync_monitor)
        if not device:
            continue  # Skip if no device is found

        print(f"Device added: {device.device_node}")
        device_info = get_device_info(device)
        if not device_info:
            continue

        # Send device info to backend
        try:
            await websocket.send(json.dumps(device_info))
            print(f"Sent device info to backend: {device_info}")
        except websockets.exceptions.ConnectionClosed:
            print("WebSocket connection closed. Cannot send device info.")
            break

        mount_point = mount_usb_device(device.device_node)
        if not mount_point:
            continue

        file_list = gather_files(mount_point)
        transfer_files(file_list)
        unmount_device(mount_point)


async def reconnect():
    """Handle reconnection to the backend."""
    while True:
        try:
            async with websockets.connect(BACKEND_URI, extra_headers=HEADERS) as websocket:
                print("Connected to backend.")

                # Coroutine to handle backend messages
                async def handle_backend_commands():
                    """Handle backend commands and confirm the USB state."""
                    while True:
                        try:
                            message = await websocket.recv()
                            print(f"Received message from backend: {message}")
                            command = json.loads(message)

                            if command.get("action") == "block":
                                print("Received block command from backend.")
                                # Implement block logic here
                                status_update = {"type": "usbStatus", "status": "blocked"}
                                await websocket.send(json.dumps(status_update))

                            elif command.get("action") == "allow":
                                print("Received allow command from backend.")
                                # Implement allow logic here
                                status_update = {"type": "usbStatus", "status": "allowed"}
                                await websocket.send(json.dumps(status_update))
                        except websockets.exceptions.ConnectionClosed:
                            print("Backend connection closed during command handling.")
                            raise  # Trigger reconnection
                        except json.JSONDecodeError:
                            print("Received invalid JSON from backend.")

                # Run USB monitoring and backend commands concurrently
                await asyncio.gather(
                    handle_backend_commands(),
                    monitor_usb_devices(websocket)
                )
        except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError) as e:
            print(f"Connection to backend lost: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Unexpected error during reconnection: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(reconnect())

