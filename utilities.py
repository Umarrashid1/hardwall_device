import subprocess
import time
from device_actions import DeviceActions
import os
import json
import asyncio


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