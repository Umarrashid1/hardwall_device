import pyudev
import json
from collections import defaultdict
from datetime import datetime


class USBEvent:
    """Base class for all USB events."""
    def __init__(self, action, devtype, devpath, properties):
        self.devtype = devtype
        self.devpath = devpath
        self.actions = defaultdict(dict)  # Group actions with their respective properties
        self.add_action(action, properties)

    def add_action(self, action, properties):
        """Add an action and its associated properties."""
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]  # Add milliseconds precision
        self.actions[action] = {"properties": properties, "timestamp": timestamp}

    def __str__(self):
        actions_str = ", ".join(f"{action} (Timestamp: {details['timestamp']})"
                                for action, details in self.actions.items())
        return f"{self.devtype} Event(s): {actions_str} at {self.devpath}"

    def get_all_actions(self):
        """Return a list of all actions with their timestamps and properties."""
        return [
            {
                "timestamp": details["timestamp"],
                "action": action,
                "devtype": self.devtype,
                "devpath": self.devpath,
                "properties": details["properties"],
            }
            for action, details in self.actions.items()
        ]


class USBDevice(USBEvent):
    """Represents a USB device."""
    def __init__(self, action, devpath, properties):
        super().__init__(action, "usb_device", devpath, properties)


class USBInterface(USBEvent):
    """Represents a USB interface."""
    def __init__(self, action, devpath, properties):
        super().__init__(action, "usb_interface", devpath, properties)


class USBMonitor:
    """Monitors and groups USB events."""
    def __init__(self):
        self.device_groups = defaultdict(lambda: {"device": None, "interfaces": []})
        self.all_events = []  # Store all events for global chronological sorting

    @staticmethod
    def get_common_path(devpath):
        """Extract the common path for grouping devices and interfaces."""
        return devpath.split(":")[0]

    def add_event(self, event):
        """Add an event to the appropriate group and the global event list."""
        common_path = self.get_common_path(event.devpath)
        if isinstance(event, USBDevice):
            if self.device_groups[common_path]["device"] is None:
                self.device_groups[common_path]["device"] = event
            else:
                device = self.device_groups[common_path]["device"]
                device.add_action(list(event.actions.keys())[0], list(event.actions.values())[0]["properties"])
        elif isinstance(event, USBInterface):
            matching_interface = next(
                (iface for iface in self.device_groups[common_path]["interfaces"]
                 if iface.devpath == event.devpath), None)
            if matching_interface:
                matching_interface.add_action(list(event.actions.keys())[0], list(event.actions.values())[0]["properties"])
            else:
                self.device_groups[common_path]["interfaces"].append(event)

        # Add the event to the global list
        self.all_events.extend(event.get_all_actions())

    def summarize(self):
        """Print a summary of grouped devices and interfaces."""
        print("\nSummary of Grouped Devices and Interfaces:")
        for path, group in self.device_groups.items():
            print(f"\nDevice Path: {path}")
            if group["device"]:
                print(group["device"])
            print("  Interfaces:")
            for interface in group["interfaces"]:
                print(interface)

    def summarize_by_time(self):
        """Print all events sorted by timestamp."""
        print("\nSummary of All Events (Chronological Order):")
        sorted_events = sorted(self.all_events, key=lambda x: x["timestamp"])
        for event in sorted_events:
            print(f"[{event['timestamp']}] {event['action']} - {event['devtype']} at {event['devpath']}")
            for key, value in event["properties"].items():
                print(f"  {key}: {value}")

    def save_summary_to_json(self, filename="usb_events.json"):
        """Save all events sorted by timestamp to a JSON file."""
        sorted_events = sorted(self.all_events, key=lambda x: x["timestamp"])
        try:
            with open(filename, "w") as json_file:
                json.dump(sorted_events, json_file, indent=4)
            print(f"\nChronological summary saved to {filename}.")
        except IOError as e:
            print(f"Error saving JSON file: {e}")

    def monitor(self):
        """Start monitoring USB events."""
        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        monitor.filter_by('usb')

        print("Monitoring USB events...")
        try:
            for device in iter(monitor.poll, None):
                action = device.action
                devtype = device.get("DEVTYPE", "Unknown")
                devpath = device.get("DEVPATH", "Unknown")
                properties = dict(device.items())

                if devtype == "usb_device":
                    event = USBDevice(action, devpath, properties)
                elif devtype == "usb_interface":
                    event = USBInterface(action, devpath, properties)
                else:
                    continue  # Skip unsupported types

                print(event)
                self.add_event(event)

        except KeyboardInterrupt:
            print("\nExiting USB monitor.")
            self.summarize_by_time()
            self.save_summary_to_json()


if __name__ == "__main__":
    monitor = USBMonitor()
    monitor.monitor()