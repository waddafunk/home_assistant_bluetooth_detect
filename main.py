#!/usr/bin/env python3
"""
Simple Bluetooth Detection Loop with Home Assistant Integration
Every 3 seconds: check if device is available and update Home Assistant
"""

import subprocess
import time
import logging
import os
import json
from datetime import datetime
from typing import List, Dict

import requests
from dotenv import load_dotenv

from healthcheck import start_health_server, health_status

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(os.getenv("APP_NAME", "Home assistant bluettoth detector"))

# Your phones MAC address
PHONE_MACS = json.loads(os.getenv("PHONE_MACS"))

# Home Assistant configuration
HA_URL = os.getenv("HA_URL", "http://localhost:8123")  # Default to localhost if not set
HA_TOKEN = os.getenv("HA_TOKEN")  # Long-lived access token from Home Assistant

# Home Assistant entity IDs for each device (will be created as binary_sensors)
# Format: binary_sensor.bluetooth_device_name
HA_ENTITY_PREFIX = "binary_sensor.bluetooth_"


# Global status for health checks



class HomeAssistantClient:
    """Client for communicating with Home Assistant REST API"""

    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.verify_connection()

    def verify_connection(self):
        """Verify connection to Home Assistant"""
        global health_status
        try:
            response = requests.get(f"{self.url}/api/", headers=self.headers, timeout=5)
            if response.status_code == 200:
                logger.info("Successfully connected to Home Assistant")
                health_status["ha_connected"] = True
            else:
                logger.error(
                    f"Failed to connect to Home Assistant: {response.status_code}"
                )
                health_status["ha_connected"] = False
        except Exception as e:
            logger.error(f"Error connecting to Home Assistant: {e}")
            health_status["ha_connected"] = False

    def update_device_state(self, device_name: str, is_present: bool):
        """Update device presence state in Home Assistant"""
        entity_id = f"{HA_ENTITY_PREFIX}{device_name.lower().replace(' ', '_')}"
        state = "on" if is_present else "off"

        payload = {
            "state": state,
            "attributes": {
                "device_class": "presence",
                "friendly_name": f"{device_name} Presence",
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                "source": "bluetooth_detection",
            },
        }

        try:
            response = requests.post(
                f"{self.url}/api/states/{entity_id}",
                json=payload,
                headers=self.headers,
                timeout=5,
            )

            if response.status_code in [200, 201]:
                logger.debug(f"Updated {entity_id} to {state}")
                return True
            else:
                logger.error(
                    f"Failed to update {entity_id}: {response.status_code} - {response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"Error updating Home Assistant state: {e}")
            return False

    def send_event(self, event_type: str, event_data: Dict):
        """Send custom event to Home Assistant"""
        try:
            response = requests.post(
                f"{self.url}/api/events/{event_type}",
                json=event_data,
                headers=self.headers,
                timeout=5,
            )

            if response.status_code in [200, 201]:
                logger.debug(f"Sent event {event_type}")
                return True
            else:
                logger.error(f"Failed to send event: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error sending event to Home Assistant: {e}")
            return False


def devices_available() -> List[str]:
    """Check if device is available using l2ping"""
    global health_status
    devices_found = []

    health_status["last_scan"] = datetime.now()

    for name, address in PHONE_MACS.items():
        try:
            logger.debug(f"Running: l2ping -c 1 -t 2 {address}; searching for {name}")
            result = subprocess.run(
                ["l2ping", "-c", "1", "-t", "2", address],
                capture_output=True,
                timeout=3,
                text=True,
            )

            logger.debug(f"l2ping returncode: {result.returncode}")
            if result.stdout:
                logger.debug(f"l2ping stdout: {result.stdout.strip()}")
            if result.stderr:
                logger.debug(f"l2ping stderr: {result.stderr.strip()}")

            if result.returncode == 0:
                logger.info(f"{name} device responded to l2ping!")
                devices_found.append(name)
                health_status["last_success"] = datetime.now()
            else:
                logger.debug(f"{name} did not respond to l2ping")

        except subprocess.TimeoutExpired:
            logger.warning(f"l2ping timed out for {name}")
        except FileNotFoundError:
            logger.error("l2ping command not found")
            health_status["error_count"] += 1
        except Exception as e:
            logger.error(f"Error running l2ping for {name}: {e}")
            health_status["error_count"] += 1

    health_status["devices_found"] = devices_found
    return devices_found


def update_home_assistant_states(
    ha_client: HomeAssistantClient, current_devices: List[str]
):
    """Update all device states in Home Assistant"""
    all_devices = list(PHONE_MACS.keys())

    for device_name in all_devices:
        is_present = device_name in current_devices
        ha_client.update_device_state(device_name, is_present)


def handle_state_change(
    ha_client: HomeAssistantClient, previous: List[str], current: List[str]
):
    """Handle state changes and notify Home Assistant"""
    # Find devices that arrived and left
    arrived = set(current) - set(previous)
    left = set(previous) - set(current)

    # Send events for arrivals
    for device in arrived:
        event_data = {
            "device": device,
            "action": "arrived",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        ha_client.send_event("bluetooth_device_arrived", event_data)
        logger.info(f"Device arrived: {device}")

    # Send events for departures
    for device in left:
        event_data = {
            "device": device,
            "action": "left",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        ha_client.send_event("bluetooth_device_left", event_data)
        logger.info(f"Device left: {device}")

    # Update all device states
    update_home_assistant_states(ha_client, current)


def main():
    global health_status

    logger.info(f"Checking devices {PHONE_MACS} every 3 seconds...")
    logger.info("Press Ctrl+C to stop")

    # Start health check server
    start_health_server()

    # Initialize Home Assistant client if configured
    ha_client = None
    if HA_TOKEN:
        try:
            ha_client = HomeAssistantClient(HA_URL, HA_TOKEN)
            logger.info("Home Assistant integration enabled")

            # Initialize all devices as "off" (not present) on startup
            initial_devices = []
            update_home_assistant_states(ha_client, initial_devices)

        except Exception as e:
            logger.error(f"Failed to initialize Home Assistant client: {e}")
            logger.info("Continuing without Home Assistant integration")
            health_status["ha_connected"] = False
    else:
        logger.warning("HA_TOKEN not set, running without Home Assistant integration")
        health_status["ha_connected"] = False

    devices_nearby = []
    previous_devices = []

    # Update status to running
    health_status["status"] = "running"

    while True:
        try:
            devices_nearby = devices_available()

            if devices_nearby:
                logger.info(f"Found {devices_nearby}")
            else:
                logger.info("No devices found nearby")

            if previous_devices != devices_nearby:
                logger.info(
                    f"State change! From {previous_devices} to {devices_nearby}"
                )

                # Update Home Assistant if client is available
                if ha_client:
                    handle_state_change(ha_client, previous_devices, devices_nearby)

            previous_devices = devices_nearby
            time.sleep(3)

        except KeyboardInterrupt:
            logger.info("Stopped by user")
            health_status["status"] = "stopping"

            # Set all devices as "off" before exiting
            if ha_client:
                logger.info("Setting all devices as away before exit...")
                update_home_assistant_states(ha_client, [])

            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            health_status["error_count"] += 1
            time.sleep(3)


if __name__ == "__main__":
    main()
