import sys
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from state_manager import StateManager
from device_actions import DeviceActions

@pytest.mark.asyncio
async def test_set_status_block_to_allow():
    # Mock dependencies
    mock_ws_client = AsyncMock()
    device_info = {
        "vendor_id": "1234",
        "product_id": "5678",
        "drivers": ["driver1"]
    }

    with patch("device_actions.DeviceActions.start_usbproxy", return_value="mock_process") as mock_start:
        state_manager = StateManager()

        # Transition to 'allow'
        await state_manager.set_status("allow", device_info=device_info, ws_client=mock_ws_client)

        # Assertions
        assert state_manager.status == "allow"
        assert state_manager.proxy_process == "mock_process"
        mock_ws_client.send_message.assert_called_with({"type": "status", "data": "allow"})
        mock_start.assert_called_once_with(
            device_info["vendor_id"],
            device_info["product_id"],
            device_info["drivers"],
            mock_ws_client
        )

@pytest.mark.asyncio
async def test_set_status_allow_to_block():
    # Mock dependencies
    mock_ws_client = AsyncMock()

    with patch("device_actions.DeviceActions.stop_usbproxy", return_value=None) as mock_stop:
        state_manager = StateManager()
        state_manager.status = "allow"
        state_manager.proxy_process = MagicMock()  # Mock process

        # Transition to 'block'
        await state_manager.set_status("block", ws_client=mock_ws_client)

        # Assertions
        assert state_manager.status == "block"
        assert state_manager.proxy_process is None
        mock_ws_client.send_message.assert_called_with({"type": "status", "data": "block"})
        mock_stop.assert_called_once_with(state_manager.proxy_process)

@pytest.mark.asyncio
async def test_set_status_missing_device_info():
    # Mock dependencies
    mock_ws_client = AsyncMock()

    state_manager = StateManager()

    # Attempt to transition to 'allow' without device_info
    await state_manager.set_status("allow", device_info=None, ws_client=mock_ws_client)

    # Assertions
    assert state_manager.status == "block"  # Status remains unchanged
    mock_ws_client.send_message.assert_called_with({"type": "status", "data": "error_missing_device_info"})

@pytest.mark.asyncio
async def test_set_status_start_usbproxy_failure():
    # Mock dependencies
    mock_ws_client = AsyncMock()
    device_info = {
        "vendor_id": "1234",
        "product_id": "5678",
        "drivers": ["driver1"]
    }

    with patch("device_actions.DeviceActions.start_usbproxy", side_effect=Exception("Failed")):
        state_manager = StateManager()

        # Attempt to transition to 'allow'
        await state_manager.set_status("allow", device_info=device_info, ws_client=mock_ws_client)

        # Assertions
        assert state_manager.status == "block"  # Status remains unchanged
        mock_ws_client.send_message.assert_called_with({"type": "status", "data": "error_allow"})