import threading
import os
import subprocess
import asyncio
import json
import time
from threading import Event
import paramiko
from scp import SCPClient
import pyudev


class DeviceActions:
    """Handles device actions like unbinding and starting USB proxy."""
    usb_log_stop_event = Event()  # Static Event shared across threads

    @staticmethod


    @staticmethod
    def start_usbproxy(vendor_id, product_id, drivers, ws_client):
        """Start USB proxy for the specified device."""
        try:
            print("Starting USBProxy...")
            command = [
                "./usb-proxy/usb-proxy",
                "--device", "fe980000.usb",
                "--driver", "fe980000.usb",
                "--vendor_id", vendor_id,
                "--product_id", product_id,
            ]
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            DeviceActions.usb_log_stop_event.clear()
            print(f"USBProxy started with PID: {process.pid}")

            if "usbhid" in drivers:
                log_file_path = './usb_log.json'
                # Clear the log file before processing
                try:
                    with open(log_file_path, 'w') as log_file:
                        log_file.truncate(0)
                    print(f"Cleared log file: {log_file_path}")
                except Exception as e:
                    print(f"Error clearing log file: {e}")
                loop = asyncio.get_running_loop()
                log_processor_thread = threading.Thread(
                    target=DeviceActions.process_usb_log,
                    args=(log_file_path, 20, ws_client, loop), 
                    daemon=True
                )
                log_processor_thread.start()

            return process
        except Exception as e:
            print(f"Failed to start USBProxy: {str(e)}")
            return None

    @staticmethod
    def stop_usbproxy(process):
        """Stop the USB proxy process."""
        try:
            DeviceActions.usb_log_stop_event.set()
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            elif process:
                process.kill()
                process.wait()
        except Exception as e:
            print(f"Failed to stop USBProxy: {str(e)}")

    @staticmethod
    def handle_usbstorage(devpath, ws_client):
        """Handle a USB storage device."""
        print(f"devpath: {devpath}")

        try:
            # Set up the udev context and look for the USB device
            context = pyudev.Context()
            device = next((dev for dev in context.list_devices(subsystem="usb") if dev.device_path == devpath), None)

            if not device:
                print(f"Device not found for path {devpath}")
                return

            # Find the associated block device (e.g., /dev/sda)
            block_device = next(
                (dev.device_node for dev in context.list_devices(subsystem="block") if device in dev.ancestors), None
            )
            if not block_device:
                print(f"No block device found for {devpath}")
                return

            # Find the first partition of the block device (e.g., /dev/sda1)
            partition = None
            for part in os.listdir("/dev"):
                if part.startswith(os.path.basename(block_device)) and part != os.path.basename(block_device):
                    partition = f"/dev/{part}"
                    break

            if not partition:
                partition = block_device  # Fall back to the whole block device (e.g., /dev/sda)

            # Mount the partition to /mnt/{partition_name}
            mount_point = f"/mnt/{os.path.basename(partition)}"
            os.makedirs(mount_point, exist_ok=True)
            print(f"partition {partition} mounted at {mount_point}")

            # Try to mount the partition
            try:
                subprocess.run(["mount", partition, mount_point], check=True, text=True)
            except subprocess.CalledProcessError as e:
                print(f"Error mounting {partition} to {mount_point}: {e}")
                return

            # Gather files and transfer them via SCP
            files = DeviceActions.gather_files(mount_point)
            DeviceActions.transfer_files_with_scp(files)

            # Prepare and send the file list message
            file_list_message = {
                "type": "fileList",
                "files": [{"path": file} for file in files]
            }
            asyncio.run(ws_client.send_message(file_list_message))

            # Unmount the device after processing
            DeviceActions.unmount_device(mount_point)

        except Exception as e:
            print(f"Error handling USB storage: {e}")
    @staticmethod
    def gather_files(mount_point):
        """Gather all files from the mounted directory."""
        file_list = []
        for root, dirs, files in os.walk(mount_point):
            for file in files:
                file_list.append(os.path.join(root, file))
        return file_list

    @staticmethod
    def unmount_device(mount_point):
        """Unmount the USB storage device."""
        try:
            subprocess.run(["umount", mount_point], check=True, text=True)
        except subprocess.CalledProcessError as e:
            print(f"Failed to unmount device: {e}")

    @staticmethod
    def transfer_files_with_scp(file_list):
        """Transfer files to the server via SCP."""
        SERVER_IP = "130.225.37.50"
        SSH_PORT = 22
        SSH_USERNAME = "ubuntu"
        KEY_FILE_PATH = "/home/guest/hardwall_device/cloud.key"
        REMOTE_DIR = "/home/ubuntu/box"

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(SERVER_IP, port=SSH_PORT, username=SSH_USERNAME, key_filename=KEY_FILE_PATH)
            with SCPClient(ssh.get_transport()) as scp:
                for file in file_list:
                    scp.put(file, REMOTE_DIR)
            ssh.close()
            return True
        except Exception as e:
            print(f"Error transferring files: {e}")
            return False

    @staticmethod
    def process_usb_log(log_file_path, batch_size, ws_client, loop):
        """Process USB log file in batches and send via WebSocket."""
        keypresses = []
        try:
            with open(log_file_path, "r") as log_file:
                while not DeviceActions.usb_log_stop_event.is_set():
                    new_line = log_file.readline()
                    if not new_line:
                        time.sleep(0.1)
                        continue
                    try:
                        log_entry = json.loads(new_line.strip())
                        keypresses.append(log_entry)
                        if len(keypresses) >= batch_size:
                            asyncio.run_coroutine_threadsafe(
                                DeviceActions.send_keypresses(keypresses, ws_client),
                                loop
                            )
                            keypresses = []
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            print(f"Error in log processing: {e}")

    @staticmethod
    async def send_keypresses(keypresses, ws_client):
        """Send keypress data to the server via WebSocket."""
        try:
            await ws_client.send_message({
                "type": "keypress_data",
                "data": keypresses
            })
        except Exception as e:
            print(f"Error sending keypress data: {e}")
