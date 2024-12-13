import threading
from threading import Event
from usb_device import USBDevice, USBEvent
import time
from device_actions import DeviceActions
import asyncio
import json
import pyudev


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
