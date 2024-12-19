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
        self.last_event_time = time.time()

    def send_device_info(self):
        """Send all device information to the backend."""
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
        #Process a USB event.
        self.reset_event_timer()
        # Filter out events caused by USBProxy
        if action in ["unbind", "remove"] and "usb-storage" in properties.get("DRIVER", ""):
            print(f"Ignoring USBProxy-related event: {action} for {devpath}")
            return

        """Add a new USB device."""
        if devtype not in ["usb_device", "usb_interface"]:
            print(f"Ignoring non-USB event: {devtype}")
            return
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
                #Store driver properties in array
                driver = properties.get("DRIVER")
                if driver:
                    device.add_driver(driver)
                    asyncio.run(self.handle_new_driver_bind(device, driver))
                return

        if devpath in self.devices:
            device = self.devices[devpath]
            event = USBEvent(action, device, devtype, properties)
            device.add_event(event)
            print(json.dumps(event.get_summary(), indent=4))
        else:
            print(f"Warning: Event for unknown device at {devpath}")

    async def handle_new_driver_bind(self, device, driver):
        """Handle a new driver bind event after the device is allowed."""
        if self.ws_client and self.ws_client.state_manager.status == "allow":
            print(f"New driver '{driver}' bound to device {device.get_device_info()}. Switching to 'block' state.")

            # Change status to block
            await self.ws_client.state_manager.set_status("block", ws_client=self.ws_client)

            # Wait 5 seconds for more events
            print("Waiting 5 seconds for additional events...")
            await asyncio.sleep(5)

            # Send updated device summary to the backend
            await self.ws_client.send_message({
                "type": "device_summary",
                "device_info": device.get_device_info(),
                "event_history": device.get_event_history()
            })
            print("Updated device summary sent to backend.")

    def monitor_events(self):
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
