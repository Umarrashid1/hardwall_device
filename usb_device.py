import json
from datetime import datetime


class USBDevice:
    #Represents a physical USB device
    def __init__(self, devtype, devpath, properties):
        self.devtype = devtype
        self.devpath = devpath
        self.vendor_id = properties.get("ID_VENDOR_ID", "Unknown")
        self.product_id = properties.get("ID_MODEL_ID", "Unknown")
        self.vendor = properties.get("ID_VENDOR", "Unknown")
        self.model = properties.get("ID_MODEL", "Unknown")
        self.serial = properties.get("ID_SERIAL", "Unknown")
        self.subsystem = properties.get("SUBSYSTEM", "Unknown")
        self.busnum = properties.get("BUSNUM", "Unknown")
        self.devnum = properties.get("DEVNUM", "Unknown")
        self.drivers = set()  # Dynamically updated drivers list
        self.events = []
        self.device_class = properties.get("ID_USB_CLASS", "Unknown")
        self.device_subclass = properties.get("ID_USB_SUBCLASS", "Unknown")
        self.device_protocol = properties.get("ID_USB_PROTOCOL", "Unknown")

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
        """Return device information as a structured dictionary."""
        return {
            "vendor_id": self.vendor_id,
            "product_id": self.product_id,
            "vendor": self.vendor,
            "model": self.model,
            "serial": self.serial,
            "subsystem": self.subsystem,
            "busnum": self.busnum,
            "devnum": self.devnum,
            "drivers": list(self.drivers) if self.drivers else [],
            "device_class": self.device_class,
            "device_subclass": self.device_subclass,
            "device_protocol": self.device_protocol,
        }

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

    @staticmethod
    def _get_timestamp():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    def get_summary(self):
        """Return a summary of this event."""
        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "device_info": self.device_info,
            "devtype": self.devtype
        }
