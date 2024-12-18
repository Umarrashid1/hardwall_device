import subprocess
import pyudev
import threading
from datetime import datetime
import json
from threading import Event
import time
import asyncio
import websockets




class USBMonitor:
    """Monitors USB events and manages devices."""

    def __init__(self, ws_client):
        self.devices = {}  # Store devices by their devpath
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
            device.print_structure()
            asyncio.run(self.ws_client.send_message({
                "type": "device_summary",
                "device_info": device.get_device_info(),
                "event_history": device.get_event_history(),
            }))




    def monitor_inactivity(self):
        """Check for inactivity and send device info if no events occur for 5 seconds."""
        while not self.stop_event.is_set():
            if not self.first_device_connected or self.last_event_time is None:
                # Skip if no device has connected yet
                time.sleep(1)
                continue

            current_time = time.time()
            if current_time - self.last_event_time >= 5:
                print("No new events for 5 seconds. Sending device info...")
                self.send_device_info()
                self.reset_event_timer()  # Avoid repeated sending
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
                print(json.dumps(event.get_summary(), indent=4))
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



class USBDevice:
    """Represents a physical USB device."""

    def __init__(self, devtype, devpath, properties):
        self.devtype = devtype
        self.devpath = devpath
        self.properties = properties
        self.vendor_id = properties.get("ID_VENDOR_ID", "Unknown")
        self.product_id = properties.get("ID_MODEL_ID", "Unknown")
        self.events = []
        self.drivers = set()  # Track unique drivers associated with this device


    def add_event(self, event):
        """Add an event to this device's history."""
        self.events.append(event)

    def add_driver(self, driver):
        """Add a driver to the device's driver list."""
        if driver and driver not in self.drivers:
            self.drivers.add(driver)
            print(f"Driver added: {driver}")

    def get_event_history(self):
        """Return a list of all events for this device."""
        return [event.get_summary() for event in self.events]

    def get_device_info(self):
        """Return a formatted string of device information."""
        return (
            f"Device Type: {self.devtype}, Path: {self.devpath}, Vendor ID: {self.vendor_id}, "
            f"Product ID: {self.product_id}, Drivers: {', '.join(self.drivers)}"
        )

    def print_structure(self):
        """Print the full structure of the device."""
        print("\n" + "=" * 40)
        print("Device Information:")
        print(self.get_device_info())
        print("\nDrivers:")
        if self.drivers:
            for driver in self.drivers:
                print(f"  - {driver}")
        else:
            print("  No drivers associated with this device.")

        print("\nEvent History:")
        if self.events:
            for event in self.events:
                print(json.dumps(event.get_summary(), indent=4))
        else:
            print("  No events recorded for this device.")
        print("=" * 40)

class USBEvent:
    """Represents a single event associated with a USB device."""

    def __init__(self, action, usb_device, devtype, properties):
        self.action = action
        self.timestamp = self._get_timestamp()
        self.device_info = usb_device.get_device_info()
        self.devtype = devtype
        self.properties = properties

    @staticmethod
    def _get_timestamp():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    def get_summary(self):
        """Return a summary of this event."""
        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "device_info": self.device_info,
            "devtype": self.devtype,
            "properties": self.properties,
        }

class DeviceActions:
    """Handles device actions like unbinding and starting USB proxy."""

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
    def start_usbproxy(devpath, vendor_id, product_id):
        """Start USB proxy for the specified device."""
        try:
            print("Starting USBProxy...")
            command = [
                "sudo", "./usb-proxy",
                "--device", devpath,
                "--vendor_id", vendor_id,
                "--product_id", product_id,
            ]
            result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            print(f"USBProxy output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to start USBProxy: {e.stderr}")


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



class WebSocketClient:
    """Manages a WebSocket connection to a server."""

    def __init__(self, server_url):
        self.server_url = server_url
        self.ws = None

    async def connect(self):
        """Establish a connection to the WebSocket server."""
        try:
            print(f"Connecting to WebSocket server at {self.server_url}...")
            self.ws = await websockets.connect(self.server_url)
            print("Connected to WebSocket server.")
        except Exception as e:
            print(f"Failed to connect to WebSocket server: {e}")
            raise

    async def send_message(self, message):
        """Send a message to the WebSocket server."""
        try:
            if self.ws:
                await self.ws.send(json.dumps(message))
                print(f"Sent message: {message}")
            else:
                print("WebSocket connection is not established.")
        except Exception as e:
            print(f"Failed to send message: {e}")

    async def close(self):
        """Close the WebSocket connection."""
        if self.ws:
            await self.ws.close()
            print("WebSocket connection closed.")

if __name__ == "__main__":
    # WebSocket server URL
    websocket_url = "ws://130.225.37.50:3000"

    # Initialize WebSocket client
    ws_client = WebSocketClient(websocket_url)

    # Connect to WebSocket server
    asyncio.run(ws_client.connect())

    # Initialize USB monitor
    monitor = USBMonitor(ws_client)

    # Start USB monitoring in a thread
    monitor_thread = threading.Thread(target=monitor.monitor_events)
    monitor_thread.start()

    # Start inactivity monitoring in a separate thread
    inactivity_thread = threading.Thread(target=monitor.monitor_inactivity)
    inactivity_thread.start()

    # Handle user input in the main thread
    monitor.handle_user_input()

    # Wait for threads to finish
    monitor_thread.join()
    inactivity_thread.join()

    # Close WebSocket connection before exiting
    asyncio.run(ws_client.close())
    print("Program terminated.")
