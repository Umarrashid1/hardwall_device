import pyudev
import asyncio
import websockets
import subprocess
import json

# Set up a connection to the backend server
async def connect_to_backend(device_info):
    uri = "ws://130.225.37.50:3000"
    async with websockets.connect(uri) as websocket:
        print("Connected to backend")

        # Convert the device info to JSON string
        device_info_str = json.dumps(device_info)

        # Send the device info to the server for analysis
        await websocket.send(device_info_str)
        print(f"Sent device info: {device_info_str}")

        # Wait for the server's decision
        response = await websocket.recv()
        print(f"Server response: {response}")

        # Based on the response, block or allow the device
        if response == "allow":
            allow_device(device_info)
        else:
            block_device(device_info)

# Function to block the USB device using USBGuard
def block_device(device_info):
    # Extract vendor and product ID
    vendor_id = device_info.get('vendor_id')
    product_id = device_info.get('product_id')

    print(f"Blocking device: Vendor ID = {vendor_id}, Product ID = {product_id}")
    subprocess.run(["usbguard", "block", f"{vendor_id}:{product_id}"])

# Function to allow the USB device using USBGuard
def allow_device(device_info):
    # Extract vendor and product ID
    vendor_id = device_info.get('vendor_id')
    product_id = device_info.get('product_id')

    print(f"Allowing device: Vendor ID = {vendor_id}, Product ID = {product_id}")
    subprocess.run(["usbguard", "allow", f"{vendor_id}:{product_id}"])

# Set up pyudev to monitor USB devices
def monitor_usb_devices():
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by('usb')  # Only monitor USB devices

    for device in iter(monitor.poll, None):
        if device.action == 'add':  # When a device is added
            print(f"Device added: {device.device_node}")
            device_info = {
                'vendor_id': device.get('ID_VENDOR_ID'),
                'product_id': device.get('ID_MODEL_ID'),
                'serial': device.get('ID_SERIAL_SHORT'),
                'model': device.get('ID_MODEL'),
                'vendor': device.get('ID_VENDOR'),
                'device_type': device.get('DEVTYPE'),
                'usb_driver': device.get('DRIVER'),
                'usb_interfaces': device.get('INTERFACE'),
                'devname': device.device_node,
                'devpath': device.device_path,
                'devtype': device.subsystem,
                'subsystem': device.subsystem,
                'busnum': device.get('BUSNUM'),
                'devnum': device.get('DEVNUM'),
                'product': device.get('ID_MODEL'),
                'max_power': device.get('MAXPOWER'),
                'usb_speed': device.get('USB_SPEED'),
                'revision': device.get('ID_REVISION'),
                'pci_id': device.get('PCI_ID'),
                'usb_class': device.get('ID_USB_CLASS'),  # USB Class Code
                'usb_protocol': device.get('ID_USB_PROTOCOL'),
                'usb_version': device.get('ID_USB_VERSION'),
                'device_node': device.device_node,
                'device_path': device.device_path,
                'ID_PATH': device.get('ID_PATH'),
                'ID_PATH_TAG': device.get('ID_PATH_TAG'),
                'ID_USB_DRIVER': device.get('ID_USB_DRIVER'),
                'ID_USB_INTERFACES': device.get('ID_USB_INTERFACES'),
                'ID_MODEL_ID': device.get('ID_MODEL_ID'),
                'ID_VENDOR_ID': device.get('ID_VENDOR_ID'),
                'ID_SERIAL': device.get('ID_SERIAL'),
                'ID_MODEL': device.get('ID_MODEL'),
                'ID_VENDOR': device.get('ID_VENDOR')
            }
            # Send the device info to the backend for analysis
            asyncio.run(connect_to_backend(device_info))

# Start monitoring USB devices
if __name__ == "__main__":
    monitor_usb_devices()

