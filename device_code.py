import os
import subprocess
from scp import SCPClient
import paramiko
import pyudev
import threading
from datetime import datetime
import json
from threading import Event
import time
import asyncio
from WebSocketClient import WebSocketClient, receive_backend_commands
from usb_device import USBDevice, USBEvent

BACKEND_URI = "ws://130.225.37.50:3000"
HEADERS = {"x-device-type": "Pi"}
MOUNT_POINT = "/mnt/usb"
SERVER_IP = "130.225.37.50"
SSH_PORT = 22
SSH_USERNAME = "ubuntu"
KEY_FILE_PATH = "/home/guest/hardwall_device/cloud.key"
REMOTE_DIR = "/home/ubuntu/box"

class StateManager:
    def __init__(self):
        self.status = "block"  # Initial state
        self.lock = asyncio.Lock()  # Prevent concurrent modifications
        self.proxy_process = None  # Track the USBProxy process

    async def set_status(self, new_status, device_info=None, ws_client=None):
        """Set the USB status and manage USBProxy accordingly."""
        async with self.lock:
            # Notify backend even if the status is already set
            if new_status == self.status:
                print(f"State is already {new_status}. Notifying backend...")
                await ws_client.send_message({
                    "type": "status",
                    "data": self.status  # Always send the current status
                })
                return

            # Handle blocking state
            if new_status == "block":
                print("Switching to 'block'. Stopping USBProxy...")
                try:
                    if self.proxy_process:
                        DeviceActions.stop_usbproxy(self.proxy_process)
                        self.proxy_process = None
                except Exception as e:
                    print(f"Error stopping USBProxy: {e}")
                    await ws_client.send_message({
                        "type": "status",
                        "data": "error_block"
                    })
                    return

            # Handle allowing state
            elif new_status == "allow":
                if not device_info:
                    print("Cannot switch to 'allow': Missing device_info.")
                    await ws_client.send_message({
                        "type": "status",
                        "data": "error_missing_device_info"
                    })
                    return

                print("Switching to 'allow'. Starting USBProxy...")
                try:
                    self.proxy_process = DeviceActions.start_usbproxy(
                        device_info["vendor_id"],
                        device_info["product_id"],
                        device_info["drivers"],
                        ws_client
                    )
                    if not self.proxy_process:
                        print("Failed to start USBProxy. Remaining in block state.")
                        return
                except Exception as e:
                    print(f"Error starting USBProxy: {e}")
                    await ws_client.send_message({
                        "type": "status",
                        "data": "error_allow"
                    })
                    return

            # Invalid status
            else:
                print(f"Invalid status '{new_status}' received. No action taken.")
                return

            # Update internal state
            self.status = new_status
            print(f"State updated to {new_status}. Notifying backend...")
            await ws_client.send_message({
                "type": "status",
                "data": self.status  # Notify backend of the updated status
            })



class USBMonitor:
    """Monitors USB events and manages devices."""
    def __init__(self, ws_client):
        self.devices = {}  # Store devices by their devpath
        self.devices_lock = threading.Lock()  # Add a lock for thread safety
        self.stop_event = Event()  # Use an Event object to manage stopping
        self.last_event_time = None  # Track the last event time
        self.first_device_connected = False  # Track if the first device has connected

        self.ws_client = ws_client  # WebSocket client instance

    def reset_event_timer(self):
        """Reset the event timer to the current time."""
        self.last_event_time = time.time()

    def send_device_info(self):
        """Send all device information to the WebSocket server."""
        for device in self.devices.values():
            if "usb-storage" in device.drivers:
                DeviceActions.handle_usbstorage(device.devpath, self.ws_client)
            print(device.get_device_info())
            asyncio.run(self.ws_client.send_message({
                "type": "device_summary",
                "device_info": device.get_device_info(),
                "event_history": device.get_event_history(),
            }))

    def monitor_inactivity(self):
        """Check for inactivity and send device info if no events occur for 5 seconds."""
        already_sent = False  # Track if the info has been sent

        while not self.stop_event.is_set():
            if not self.first_device_connected or self.last_event_time is None:
                # Skip if no device has connected yet
                time.sleep(1)
                continue

            current_time = time.time()
            if current_time - self.last_event_time >= 5:
                if not already_sent:  # Only send if it hasn't been sent already
                    print("No new events for 5 seconds. Sending device info...")
                    self.send_device_info()
                    already_sent = True  # Mark as sent
            else:
                already_sent = False  # Reset if activity resumes
            time.sleep(1)  # Check every second

    def add_device(self, devtype, devpath, properties):
        """Add a new USB device."""
        if devpath not in self.devices:
            self.devices[devpath] = USBDevice(devtype, devpath, properties)
            print(f"Device added: {self.devices[devpath].get_device_info()}")

            if not self.first_device_connected:
                # Start the inactivity timer when the first device connects
                self.first_device_connected = True
                self.reset_event_timer()

    def add_event(self, action, devtype, devpath, properties):
        """Process a USB event."""
        self.reset_event_timer()  # Reset the inactivity timer
        # Ensure the event is valid
        if devtype not in ["usb_device", "usb_interface"]:
            print(f"Ignoring non-USB event: {devtype}")
            return

        # Handle "add" action for devices
        if action == "add" and devtype == "usb_device":
            if devpath not in self.devices:
                self.add_device(devtype, devpath, properties)

        # Handle interface events by finding the parent device
        if devtype == "usb_interface":
            # Find the parent device by trimming the interface part from the devpath
            parent_path = devpath.rsplit('/', 1)[0]
            if parent_path in self.devices:
                device = self.devices[parent_path]
                event = USBEvent(action, device, devtype, properties)
                device.add_event(event)
                driver = properties.get("DRIVER")
                if driver:
                    device.add_driver(driver)
                #print(json.dumps(event.get_summary(), indent=4))
                return

        # Handle other events or log warnings
        if devpath in self.devices:
            device = self.devices[devpath]
            event = USBEvent(action, device, devtype, properties)
            device.add_event(event)
            print(json.dumps(event.get_summary(), indent=4))
        else:
            print(f"Warning: Event for unknown device at {devpath}")

    def handle_user_input(self):
        """placeholder for interoupt to block/allow from cloud."""


    def monitor_events(self):
        """Start monitoring USB events."""
        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by('usb')


        print("Monitoring USB events... Press Enter to stop.")
        try:
            while not self.stop_event.is_set():  # Continue until stop_event is set
                device = monitor.poll(timeout=1)  # Timeout allows stop_event to be checked
                if device is None:
                    continue
                action = device.action
                devtype = device.get("DEVTYPE", "Unknown")
                devpath = device.get("DEVPATH", "Unknown")
                properties = dict(device.items())

                self.add_event(action, devtype, devpath, properties)
        except Exception as e:
            print(f"Error during monitoring: {e}")






class DeviceActions:
    """Handles device actions like unbinding and starting USB proxy."""
    usb_log_stop_event = Event()  # Static Event shared across threads
    @staticmethod
    def unbind_device(devpath):
        """Unbind the specified device."""
        try:
            print(f"Unbinding device at {devpath}...")
            unbind_command = f"echo '{devpath}' | sudo tee /sys/bus/usb/drivers/hub/unbind"
            result = subprocess.run(unbind_command, shell=True, check=True, text=True)
            print(f"Device unbound successfully: {result.stdout}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to unbind device: {e.stderr}")

    @staticmethod
    def start_usbproxy( vendor_id, product_id, drivers, ws_client):
        """Start USB proxy for the specified device."""
        try:
            print("Starting USBProxy...")
            command = [
                "sudo", "./usb-proxy",
                "--device", "fe980000.usb",
                "--driver", "fe980000.usb",
                "--vendor_id", vendor_id,
                "--product_id", product_id,
            ]
            # Start USBProxy process
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Clear stop event to ensure the log thread starts in a running state
            DeviceActions.usb_log_stop_event.clear()
            print(f"USBProxy started with PID: {process.pid}")

            if "usbhid" in drivers:

                log_file_path = 'usb_log.json'

                loop = asyncio.get_running_loop()
                log_processor_thread = threading.Thread(
                    target=Utilities.process_usb_log,
                    args=(log_file_path, 20, ws_client, loop),  # Process 20 keypresses at a time
                    daemon=True  # Ensures thread exits when the main program exits
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
            # Signal the log processing thread to stop
            DeviceActions.usb_log_stop_event.set()
            print("stop_event set for USBProxy log thread.")

            # Terminate the USBProxy process
            if process and process.poll() is None:
                print(f"Attempting to terminate USBProxy with PID {process.pid}...")
                process.terminate()
                try:
                    process.wait(timeout=5)
                    print(f"USBProxy with PID {process.pid} terminated gracefully.")
                except subprocess.TimeoutExpired:
                    print(f"Graceful termination failed. Forcibly killing USBProxy with PID {process.pid}...")
                    process.kill()
                    process.wait()
                    print(f"USBProxy with PID {process.pid} killed.")
            elif process and process.poll() is not None:
                print(f"USBProxy with PID {process.pid} is already terminated.")
            else:
                print("No process to terminate.")
        except Exception as e:
            print(f"Failed to stop USBProxy: {str(e)}")

    @staticmethod
    def handle_usbstorage(devpath, ws_client):
        """Handle a USB storage device by mounting, gathering files, transferring, and cleaning up."""
        try:
            context = pyudev.Context()

            # Find the device using its devpath
            print(f"Looking for USB device: {devpath}")
            device = None
            for dev in context.list_devices(subsystem="usb"):
                if dev.device_path == devpath:
                    device = dev
                    break

            if not device:
                print(f"Error: Device not found for path {devpath}")
                return

            # Find associated block device
            block_device = None
            for dev in context.list_devices(subsystem="block"):
                if device in dev.ancestors:
                    block_device = dev.device_node
                    print(f"Found block device: {block_device}")
                    break

            if not block_device:
                print(f"Error: No block device found for {devpath}")
                return

            # Handle partitions or use block device directly
            partition = None
            for part in os.listdir("/dev"):
                if part.startswith(os.path.basename(block_device)) and part != os.path.basename(block_device):
                    partition = f"/dev/{part}"
                    break
            partition = partition or block_device

            # Define dynamic mount point
            mount_point = f"/mnt/{os.path.basename(partition)}"
            print(f"Attempting to mount {partition} to {mount_point}")

            # Ensure the mount point exists
            os.makedirs(mount_point, exist_ok=True)

            # Mount the partition
            subprocess.run(["sudo", "mount", partition, mount_point], check=True, text=True)
            print(f"Mounted {partition} at {mount_point}")

            # Gather files
            files = DeviceActions.gather_files(mount_point)
            print(f"Files gathered from {mount_point}: {files}")

            # Transfer files
            transfer_result = DeviceActions.transfer_files_with_scp(files)
            if transfer_result:
                print("Files transferred successfully.")
            else:
                print("File transfer encountered issues.")

            file_list_message = {
                "type": "fileList",
                "files": [{"path": file} for file in files]
            }
            asyncio.run(ws_client.send_message(file_list_message))
            print("Sent file list to backend:", file_list_message)

            # Unmount the device
            DeviceActions.unmount_device(mount_point)
            print(f"Device unmounted from {mount_point}")

        except subprocess.CalledProcessError as e:
            print(f"Failed to mount or process USB storage device: {e}")
        except Exception as e:
            print(f"An error occurred while handling USB storage: {e}")

    @staticmethod
    def gather_files(mount_point):
        """Gather all files from the mounted directory."""
        file_list = []
        for root, dirs, files in os.walk(mount_point):
            for file in files:
                file_path = os.path.join(root, file)
                file_list.append(file_path)
        return file_list

    @staticmethod
    def unmount_device(mount_point):
        """Unmount the USB storage device."""
        try:
            subprocess.run(
                ["sudo", "umount", mount_point],
                check=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            print(f"Failed to unmount device: {e}")

    @staticmethod
    def transfer_files_with_scp(file_list):
        """Transfer files to the server via SCP."""
        try:
            # Set server details
            SERVER_IP = "130.225.37.50"
            SSH_PORT = 22
            SSH_USERNAME = "ubuntu"
            KEY_FILE_PATH = "/home/guest/hardwall_device/cloud.key"
            REMOTE_DIR = "/home/ubuntu/box"

            print("Establishing SSH connection for SCP...")
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(SERVER_IP, port=SSH_PORT, username=SSH_USERNAME, key_filename=KEY_FILE_PATH)
            print(f"Connected to {SERVER_IP} via SSH.")

            # Use SCP to transfer files
            with SCPClient(ssh.get_transport()) as scp:
                for file in file_list:
                    print(f"Transferring file: {file}")
                    scp.put(file, REMOTE_DIR)
                    print(f"File {file} transferred to {REMOTE_DIR}")

            ssh.close()
            print("SSH connection closed after SCP transfer.")
            return True
        except Exception as e:
            print(f"Error during file transfer: {e}")
            return False




class Utilities:
    """Provides utility functions for subprocess handling and logging."""
    @staticmethod
    def run_command(command, description):
        """Run a system command and handle errors."""
        try:
            print(f"Running command: {command}")
            result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            print(f"{description} succeeded: {result.stdout}")
        except subprocess.CalledProcessError as e:
            print(f"{description} failed: {e.stderr}")

    @staticmethod
    def process_usb_log(log_file_path, batch_size, ws_client, loop):
        """Process USB log file in batches and send via WebSocket."""
        print(f"Starting to process USB log file: {log_file_path}")
        keypresses = []  # Initialize the batch
        last_position = 0  # Track the last read position
        try:
            # Open the file in read mode with buffering disabled
            with open(log_file_path, "r") as log_file:
                log_file.seek(0, os.SEEK_END)  # Seek to the end of the file initially

                while not DeviceActions.usb_log_stop_event.is_set():  # Check stop_event to terminate gracefully
                    log_file.seek(last_position)  # Seek to the last read position
                    new_line = log_file.readline()
                    if not new_line:
                        time.sleep(0.1)
                        continue
                    try:
                        # Parse the JSON log entry
                        log_entry = json.loads(new_line.strip())
                        keypresses.append(log_entry)  # Add to batch
                        print(f"Added to batch: {log_entry}")

                        # Check if the batch is ready
                        if len(keypresses) >= batch_size:
                            print(f"Batch ready: {keypresses}")
                            # Schedule the coroutine in the running event loop
                            asyncio.run_coroutine_threadsafe(
                                send_keypresses(keypresses, ws_client),
                                loop
                            )
                            keypresses = []  # Clear batch after processing

                        # Update the last read position
                        last_position = log_file.tell()

                    except json.JSONDecodeError as e:
                        print(f"Error parsing log entry: {new_line.strip()} -> {e}")

        except Exception as e:
            print(f"Error in process_usb_log: {e}")


async def send_keypresses(keypresses, ws_client):
    """Send keypress data to the server via WebSocket."""
    try:
        # Prepare the message
        message = {
            "type": "keypress_data",
            "data": keypresses
        }

        # Use the WebSocketClient to send the message
        await ws_client.send_message(message)
        print(f"[INFO] Sent {len(keypresses)} keypresses.")
    except Exception as e:
        print(f"[ERROR] Failed to send keypress data: {e}")










async def main():
    state_manager = StateManager()
    ws_client = WebSocketClient(BACKEND_URI)

    # Connect to the backend
    await ws_client.connect(state_manager)

    # Initialize USB monitor
    monitor = USBMonitor(ws_client)

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
