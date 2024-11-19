import os
import subprocess
import pyudev
import asyncio
import websockets
import json
import paramiko
from scp import SCPClient
import time


def get_device_info(device):
    """Get USB device information and check if it is a mass storage device."""
    device_id = f"{device.get('ID_VENDOR_ID')}:{device.get('ID_MODEL_ID')}"
    print(f"Detected device with ID: {device_id}")

    try:
        result = subprocess.run(['lsusb', '-v', '-d', device_id], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if result.returncode == 0 and "Mass Storage" in result.stdout.decode():
            print("Device is a USB Mass Storage device.")
            return result.stdout.decode()
        else:
            print("Device is not a USB Mass Storage device.")
            return None
    except Exception as e:
        print(f"An error occurred while running lsusb: {e}")
        return None


def get_block_device_from_device_node(device_node):
    """Find and return the block device associated with the given USB device node."""
    context = pyudev.Context()

    try:
        device = pyudev.Devices.from_device_file(context, device_node)
        print(f"Looking for block device related to: {device_node}")

        for _ in range(10):  # Retry for up to 5 seconds
            for dev in context.list_devices(subsystem='block'):
                if device in dev.ancestors:
                    print(f"Found block device: {dev.device_node}")
                    return dev.device_node
            time.sleep(0.5)  # Wait 500ms before retrying
    except Exception as e:
        print(f"Error finding block device: {e}")

    print("No block device found for this USB device.")
    return None


def mount_usb_device(device_node):
    """Mount the USB device and return the mount point."""
    mount_point = "/mnt/usb"
    os.makedirs(mount_point, exist_ok=True)

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
        print(f"Using device: {partition}")

        subprocess.run(["sudo", "mount", partition, mount_point], check=True)
        print(f"Mounted {partition} at {mount_point}")
        return mount_point
    except subprocess.CalledProcessError as e:
        print(f"Failed to mount device: {e}")
        return None


def gather_files(mount_point):
    """Gather all files in the mounted directory."""
    file_list = []
    for root, _, files in os.walk(mount_point):
        for file in files:
            file_path = os.path.join(root, file)
            file_list.append(file_path)
    # Commented out to reduce terminal output
    # print(f"Files gathered: {file_list}")
    return file_list



def create_ssh_client(server_ip, port, username, key_file_path):
    """Create and return an SSH client."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(server_ip, port=port, username=username, key_filename=key_file_path, timeout=10)
        print(f"Connected to {server_ip} via SSH.")
        return ssh
    except Exception as e:
        print(f"Failed to connect to {server_ip}: {e}")
        return None


def send_files_via_scp(local_dir, remote_dir, ssh_client):
    """Send all files in the local directory to the remote directory via SCP."""
    try:
        with SCPClient(ssh_client.get_transport()) as scp:
            for root, _, files in os.walk(local_dir):
                for file in files:
                    local_path = os.path.join(root, file)
                    # Commented out to reduce terminal output
                    # print(f"Transferring file via SCP: {local_path} -> {remote_dir}")
                    scp.put(local_path, remote_dir)
                    # print(f"Transferred {local_path} successfully.")
    except Exception as e:
        print(f"Error transferring files via SCP: {e}")



async def connect_to_backend(lsusb_output, file_list):
    """Connect to the backend server via WebSocket, send metadata, and maintain the connection."""
    uri = "ws://130.225.37.50:3000"  # Backend WebSocket server
    headers = {"x-device-type": "Pi"}  # Required custom headers

    try:
        async with websockets.connect(uri, extra_headers=headers) as websocket:
            print("Connected to backend with headers:", headers)

            # Function to send periodic status updates
            async def send_status_updates():
                while True:
                    try:
                        status_update = {"type": "status", "status": "active"}
                        await websocket.send(json.dumps(status_update))
                        print("Sent status update to backend")
                        await asyncio.sleep(30)  # Every 30 seconds
                    except websockets.exceptions.ConnectionClosed:
                        print("WebSocket connection closed. Stopping status updates.")
                        break

            # Start sending status updates
            asyncio.create_task(send_status_updates())

            # Prepare and send metadata
            data = {
                "type": "deviceInfo",
                "deviceInfo": {
                    "lsusb_output": lsusb_output,
                    "files": file_list
                }
            }
            payload = json.dumps(data)
            print(f"Sending metadata to backend: {payload}")
            await websocket.send(payload)

            # Handle backend responses
            while True:
                try:
                    response = await websocket.recv()
                    print(f"Backend response: {response}")

                    # Handle specific backend actions
                    try:
                        response_data = json.loads(response)
                        if response_data.get("action") == "block":
                            print("Backend issued a block command.")
                            # Implement block logic here if needed
                        elif response_data.get("action") == "allow":
                            print("Backend issued an allow command.")
                            # Implement allow logic here if needed
                        else:
                            print(f"Unexpected action from backend: {response_data}")
                    except json.JSONDecodeError:
                        print("Received malformed JSON from backend.")
                except websockets.exceptions.ConnectionClosed:
                    print("WebSocket connection closed by backend.")
                    break
    except Exception as e:
        print(f"WebSocket connection failed: {e}")






def monitor_usb_devices():
    """Monitor USB devices, transfer files with SCP, and notify backend."""
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by('usb')

    server_ip = "130.225.37.50"
    port = 22
    username = "ubuntu"
    key_file_path = "/home/guest/hardwall_device/cloud.key"
    remote_dir = "/home/ubuntu/box"

    print("Monitoring USB devices...")

    for device in iter(monitor.poll, None):
        if device.action == 'add' and 'DEVNAME' in device:
            device_node = device.device_node
            print(f"Device added: {device_node}")

            # Get USB metadata
            lsusb_output = get_device_info(device)
            if not lsusb_output:
                continue

            # Mount the device
            mount_point = mount_usb_device(device_node)
            if not mount_point:
                continue

            # Gather files
            file_list = gather_files(mount_point)

            # Transfer files via SCP
            ssh_client = create_ssh_client(server_ip, port, username, key_file_path)
            if ssh_client:
                try:
                    send_files_via_scp(mount_point, remote_dir, ssh_client)
                finally:
                    ssh_client.close()
                    try:
                        subprocess.run(["sudo", "umount", mount_point], check=True)
                        print(f"Unmounted {mount_point}")
                    except subprocess.CalledProcessError as e:
                        print(f"Failed to unmount {mount_point}: {e}")

            # Send metadata via WebSocket
            response = asyncio.run(connect_to_backend(lsusb_output, file_list))

            # Handle backend response
            if response:
                action = response.get("action")
                if action == "block":
                    print("Backend blocked the device. Unmounting...")

                elif action == "allow":
                    print("Backend allowed the device.")
                else:
                    print(f"Unexpected backend action: {action}. Assuming block.")

            else:
                print("No valid response from backend. Assuming block.")




if __name__ == "__main__":
    monitor_usb_devices()

