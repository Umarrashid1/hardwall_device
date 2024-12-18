import asyncio
from device_actions import DeviceActions

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