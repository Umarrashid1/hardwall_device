import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from usb_monitor import USBMonitor

@pytest.fixture
def mock_ws_client():
    return AsyncMock()

@pytest.fixture
def usb_monitor(mock_ws_client):
    return USBMonitor(mock_ws_client)


def test_add_device(usb_monitor):
    # Mock device properties
    devtype = "usb_device"
    devpath = "/dev/bus/usb/001/001"
    properties = {"ID_VENDOR_ID": "1234", "ID_PRODUCT_ID": "5678"}

    # Add device
    usb_monitor.add_device(devtype, devpath, properties)

    # Verify the device is added
    assert devpath in usb_monitor.devices
    device = usb_monitor.devices[devpath]
    assert device.devtype == devtype
    assert device.devpath == devpath
    assert device.vendor_id == "1234"
    assert device.product_id == "5678"

def test_add_event(usb_monitor):
    # Mock event properties
    devtype = "usb_device"
    devpath = "/dev/bus/usb/001/001"
    action = "add"
    properties = {"ID_VENDOR_ID": "1234", "ID_PRODUCT_ID": "5678"}

    # Add an event
    usb_monitor.add_event(action, devtype, devpath, properties)

    # Verify the event is added
    assert devpath in usb_monitor.devices
    device = usb_monitor.devices[devpath]
    assert len(device.events) == 1
    assert device.events[0].action == "add"

@pytest.mark.asyncio
async def test_send_device_info(usb_monitor, mock_ws_client):
    # Add a mock device
    devpath = "/dev/bus/usb/001/001"
    mock_device = MagicMock()
    mock_device.get_device_info.return_value = {"vendor_id": "1234", "product_id": "5678"}
    mock_device.get_event_history.return_value = []

    usb_monitor.devices[devpath] = mock_device

    # Call send_device_info
    usb_monitor.send_device_info()

    # Verify WebSocket message is sent
    mock_ws_client.send_message.assert_called_with({
        "type": "device_summary",
        "device_info": mock_device.get_device_info(),
        "event_history": mock_device.get_event_history(),
    })

def test_monitor_inactivity(usb_monitor):
    # Simulate connected device and inactivity
    usb_monitor.first_device_connected = True
    usb_monitor.last_event_time = time.time() - 6  # Simulate 6 seconds of inactivity

    with patch.object(usb_monitor, "send_device_info") as mock_send_info:
        usb_monitor.monitor_inactivity()

    # Verify `send_device_info` was called
    mock_send_info.assert_called_once()

def test_monitor_events():
    # Mock pyudev.Monitor
    with patch("pyudev.Monitor.from_netlink") as mock_monitor:
        mock_device = MagicMock()
        mock_device.action = "add"
        mock_device.get.return_value = "usb_device"
        mock_device.items.return_value = {"DEVPATH": "/dev/bus/usb/001/001"}

        mock_monitor.return_value.poll.return_value = mock_device

        # Initialize USBMonitor
        mock_ws_client = AsyncMock()
        usb_monitor = USBMonitor(mock_ws_client)

        with patch.object(usb_monitor, "add_event") as mock_add_event:
            usb_monitor.monitor_events()

        # Verify `add_event` was called
        mock_add_event.assert_called_once_with(
            action="add",
            devtype="usb_device",
            devpath="/dev/bus/usb/001/001",
            properties={"DEVPATH": "/dev/bus/usb/001/001"}
        )