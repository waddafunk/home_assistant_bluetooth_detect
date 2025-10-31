#!/usr/bin/env python3
"""
Simple Bluetooth Detection Loop with Home Assistant Integration
Every 30 seconds: check if device is available and update Home Assistant
Added: AWAY_TIMEOUT feature to prevent immediate "away" status
Enhanced: Added "everybody home" and "nobody home" binary sensors
Improved: Using hcitool instead of l2ping for better reliability
Added: Automatic Bluetooth adapter reset on persistent errors
"""

import subprocess
import time
import logging
import os
import json
from datetime import datetime, timedelta
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
logger = logging.getLogger(os.getenv("APP_NAME", "Home assistant bluetooth detector"))

# Your phones MAC address
PHONE_MACS = json.loads(os.getenv("PHONE_MACS"))

# Home Assistant configuration
HA_URL = os.getenv("HA_URL", "http://localhost:8123")  # Default to localhost if not set
HA_TOKEN = os.getenv("HA_TOKEN")  # Long-lived access token from Home Assistant

# Away timeout configuration (in minutes)
AWAY_TIMEOUT_MINUTES = int(os.getenv("AWAY_TIMEOUT", "5"))  # Default 5 minutes

# Scan interval (in seconds)
SCAN_INTERVAL = int(os.getenv("SECONDS_BETWEEN_PINGS", 30))

# Bluetooth adapter reset threshold
ERROR_THRESHOLD_FOR_RESET = int(os.getenv("BT_ERROR_THRESHOLD", "15"))

# Home Assistant entity IDs for each device (will be created as binary_sensors)
# Format: binary_sensor.bluetooth_device_name
HA_ENTITY_PREFIX = "binary_sensor.bluetooth_"

# Group sensor entity IDs
HA_EVERYBODY_HOME_ENTITY = "binary_sensor.bluetooth_everybody_home"
HA_NOBODY_HOME_ENTITY = "binary_sensor.bluetooth_nobody_home"
HA_ANYBODY_HOME_ENTITY = "binary_sensor.bluetooth_anybody_home"

# Global status for health checks
# Device tracking for timeout functionality
device_last_seen = {}  # Track when each device was last detected
device_reported_states = {}  # Track what we last reported to HA for each device
consecutive_scan_failures = 0  # Track consecutive failures


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
                "away_timeout_minutes": AWAY_TIMEOUT_MINUTES,
                "detection_method": "hcitool",
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

    def update_group_sensors(self):
        """Update the everybody home, nobody home, and anybody home binary sensors"""
        # Get current states
        present_devices = [name for name, state in device_reported_states.items() if state]
        total_devices = len(PHONE_MACS)
        present_count = len(present_devices)
        
        everybody_home = present_count == total_devices and total_devices > 0
        nobody_home = present_count == 0
        anybody_home = present_count > 0
        
        # Common attributes for all group sensors
        common_attributes = {
            "device_class": "presence",
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "bluetooth_detection",
            "total_devices": total_devices,
            "present_devices": present_count,
            "present_device_list": present_devices,
            "away_timeout_minutes": AWAY_TIMEOUT_MINUTES,
            "detection_method": "hcitool",
        }
        
        # Update everybody home sensor
        everybody_payload = {
            "state": "on" if everybody_home else "off",
            "attributes": {
                **common_attributes,
                "friendly_name": "Everybody Home",
            },
        }
        
        # Update nobody home sensor
        nobody_payload = {
            "state": "on" if nobody_home else "off",
            "attributes": {
                **common_attributes,
                "friendly_name": "Nobody Home",
            },
        }
        
        # Update anybody home sensor
        anybody_payload = {
            "state": "on" if anybody_home else "off",
            "attributes": {
                **common_attributes,
                "friendly_name": "Anybody Home",
            },
        }
        
        # Send updates to Home Assistant
        success = True
        
        sensors_to_update = [
            (HA_EVERYBODY_HOME_ENTITY, everybody_payload, "everybody home"),
            (HA_NOBODY_HOME_ENTITY, nobody_payload, "nobody home"),
            (HA_ANYBODY_HOME_ENTITY, anybody_payload, "anybody home"),
        ]
        
        for entity_id, payload, sensor_name in sensors_to_update:
            try:
                response = requests.post(
                    f"{self.url}/api/states/{entity_id}",
                    json=payload,
                    headers=self.headers,
                    timeout=5,
                )
                
                if response.status_code in [200, 201]:
                    logger.debug(f"Updated {entity_id} to {payload['state']}")
                else:
                    logger.error(f"Failed to update {entity_id}: {response.status_code}")
                    success = False
                    
            except Exception as e:
                logger.error(f"Error updating {sensor_name} sensor: {e}")
                success = False
            
        return success

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


def reset_bluetooth_adapter():
    """Reset Bluetooth adapter to recover from errors"""
    logger.warning("Resetting Bluetooth adapter...")
    try:
        # Bring adapter down
        result = subprocess.run(
            ["sudo", "hciconfig", "hci0", "down"],
            capture_output=True,
            timeout=5,
            text=True,
        )
        if result.returncode != 0:
            logger.error(f"Failed to bring adapter down: {result.stderr}")
            return False
        
        time.sleep(2)
        
        # Bring adapter up
        result = subprocess.run(
            ["sudo", "hciconfig", "hci0", "up"],
            capture_output=True,
            timeout=5,
            text=True,
        )
        if result.returncode != 0:
            logger.error(f"Failed to bring adapter up: {result.stderr}")
            return False
        
        time.sleep(2)
        
        logger.info("✓ Bluetooth adapter reset complete")
        return True
        
    except Exception as e:
        logger.error(f"Failed to reset Bluetooth adapter: {e}")
        return False


def check_bluetooth_adapter():
    """Check if Bluetooth adapter is operational"""
    try:
        result = subprocess.run(
            ["hciconfig", "hci0"],
            capture_output=True,
            timeout=5,
            text=True,
        )
        
        if result.returncode == 0 and "UP RUNNING" in result.stdout:
            return True
        else:
            logger.warning("Bluetooth adapter not in UP RUNNING state")
            return False
            
    except Exception as e:
        logger.error(f"Error checking Bluetooth adapter: {e}")
        return False


def devices_available() -> List[str]:
    """Check if devices are available using hcitool name command"""
    global health_status, consecutive_scan_failures
    devices_found = []
    scan_had_errors = False

    health_status["last_scan"] = datetime.now()

    for name, address in PHONE_MACS.items():
        try:
            logger.debug(f"Running: hcitool name {address}; searching for {name}")
            
            # hcitool name will return the device name if available, or error if not
            result = subprocess.run(
                ["hcitool", "name", address],
                capture_output=True,
                timeout=5,
                text=True,
            )

            logger.debug(f"hcitool returncode: {result.returncode}")
            if result.stdout:
                logger.debug(f"hcitool stdout: {result.stdout.strip()}")
            if result.stderr:
                logger.debug(f"hcitool stderr: {result.stderr.strip()}")

            # If we got a device name back (non-empty stdout and return code 0), device is present
            if result.returncode == 0 and result.stdout.strip():
                logger.info(f"✓ {name} device responded to hcitool name!")
                devices_found.append(name)
                health_status["last_success"] = datetime.now()
            else:
                logger.debug(f"✗ {name} did not respond to hcitool name")

        except subprocess.TimeoutExpired:
            logger.warning(f"⏱ hcitool timed out for {name}")
            scan_had_errors = True
        except FileNotFoundError:
            logger.error("❌ hcitool command not found - is bluez-tools installed?")
            health_status["error_count"] += 1
            scan_had_errors = True
        except Exception as e:
            logger.error(f"❌ Error running hcitool for {name}: {e}")
            health_status["error_count"] += 1
            scan_had_errors = True

    # Track consecutive failures for adapter reset logic
    if scan_had_errors:
        consecutive_scan_failures += 1
    else:
        consecutive_scan_failures = 0

    health_status["devices_found"] = devices_found
    health_status["consecutive_failures"] = consecutive_scan_failures
    
    return devices_found


def update_device_tracking(detected_devices: List[str]):
    """Update device tracking with timeout logic"""
    global device_last_seen, device_reported_states

    current_time = datetime.now()
    timeout_delta = timedelta(minutes=AWAY_TIMEOUT_MINUTES)

    # Update last seen time for detected devices
    for device in detected_devices:
        device_last_seen[device] = current_time

    # Initialize tracking for devices we haven't seen before
    for device in PHONE_MACS.keys():
        if device not in device_last_seen:
            # For new devices, consider them as "away" initially
            device_last_seen[device] = (
                current_time - timeout_delta - timedelta(seconds=1)
            )
        if device not in device_reported_states:
            device_reported_states[device] = False  # Start as away

    # Determine current presence status for each device
    devices_to_report_present = []
    devices_to_report_away = []

    for device in PHONE_MACS.keys():
        last_seen = device_last_seen.get(device)
        time_since_seen = (
            current_time - last_seen
            if last_seen
            else timeout_delta + timedelta(seconds=1)
        )

        # Device is considered present if detected recently
        is_currently_present = device in detected_devices

        # Device should be reported as present if:
        # 1. It's currently detected, OR
        # 2. It was detected within the timeout period
        should_report_present = is_currently_present or time_since_seen <= timeout_delta

        # Check if we need to update the reported state
        last_reported_state = device_reported_states.get(device, False)

        if should_report_present and not last_reported_state:
            # Device should be marked as present (arrival)
            devices_to_report_present.append(device)
            device_reported_states[device] = True
            logger.info(f"🟢 Device {device} marked as PRESENT")

        elif not should_report_present and last_reported_state:
            # Device should be marked as away (departure after timeout)
            devices_to_report_away.append(device)
            device_reported_states[device] = False
            time_away = time_since_seen.total_seconds() / 60  # Convert to minutes
            logger.info(
                f"🔴 Device {device} marked as AWAY (not seen for {time_away:.1f} minutes)"
            )

        elif is_currently_present and should_report_present:
            # Device is still present (no state change needed, but log detection)
            logger.debug(f"✓ Device {device} still present")

        elif not should_report_present:
            # Device is still away but within timeout period
            if time_since_seen <= timeout_delta:
                time_away = time_since_seen.total_seconds() / 60
                logger.debug(
                    f"⏳ Device {device} not detected for {time_away:.1f} minutes (within {AWAY_TIMEOUT_MINUTES} min timeout)"
                )

    return devices_to_report_present, devices_to_report_away


def update_home_assistant_states(ha_client: HomeAssistantClient):
    """Update all device states in Home Assistant based on current tracked states"""
    # Update individual device states
    for device_name, is_present in device_reported_states.items():
        ha_client.update_device_state(device_name, is_present)
    
    # Update group sensors
    ha_client.update_group_sensors()


def handle_state_changes(
    ha_client: HomeAssistantClient, devices_arrived: List[str], devices_left: List[str]
):
    """Handle state changes and notify Home Assistant"""
    
    # Track if we need to send group events
    group_state_changed = len(devices_arrived) > 0 or len(devices_left) > 0

    # Send events for arrivals
    for device in devices_arrived:
        event_data = {
            "device": device,
            "action": "arrived",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timeout_minutes": AWAY_TIMEOUT_MINUTES,
        }
        ha_client.send_event("bluetooth_device_arrived", event_data)
        logger.info(f"🟢 Device arrived: {device}")

    # Send events for departures
    for device in devices_left:
        event_data = {
            "device": device,
            "action": "left",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timeout_minutes": AWAY_TIMEOUT_MINUTES,
        }
        ha_client.send_event("bluetooth_device_left", event_data)
        logger.info(
            f"🔴 Device left: {device} (after {AWAY_TIMEOUT_MINUTES} minute timeout)"
        )

    # Update all device states in HA (including group sensors)
    update_home_assistant_states(ha_client)
    
    # Send group events if state changed
    if group_state_changed:
        present_devices = [name for name, state in device_reported_states.items() if state]
        total_devices = len(PHONE_MACS)
        present_count = len(present_devices)
        
        everybody_home = present_count == total_devices and total_devices > 0
        nobody_home = present_count == 0
        anybody_home = present_count > 0
        
        if everybody_home:
            event_data = {
                "action": "everybody_home",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "present_devices": present_devices,
                "total_devices": total_devices,
            }
            ha_client.send_event("bluetooth_everybody_home", event_data)
            logger.info("🏠 Everybody is now home!")
            
        elif nobody_home:
            event_data = {
                "action": "nobody_home", 
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_devices": total_devices,
            }
            ha_client.send_event("bluetooth_nobody_home", event_data)
            logger.info("🚪 Nobody is home now!")
            
        # Send anybody home event (this will be true whenever someone arrives and nobody was home)
        if anybody_home and devices_arrived:
            # Check if we transitioned from nobody home to somebody home
            previous_count = present_count - len(devices_arrived) + len(devices_left)
            if previous_count == 0:
                event_data = {
                    "action": "anybody_home",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "present_devices": present_devices,
                    "first_person_home": devices_arrived[0] if devices_arrived else None,
                    "total_devices": total_devices,
                }
                ha_client.send_event("bluetooth_anybody_home", event_data)
                logger.info(f"👋 First person home: {devices_arrived[0]}!")


def main():
    global health_status, consecutive_scan_failures

    logger.info(f"🔷 Bluetooth Detection Service Starting")
    logger.info(f"📱 Monitoring devices: {list(PHONE_MACS.keys())}")
    logger.info(f"⏱ Scan interval: {SCAN_INTERVAL} seconds")
    logger.info(f"⏳ Away timeout: {AWAY_TIMEOUT_MINUTES} minutes")
    logger.info(f"🔄 Auto-reset threshold: {ERROR_THRESHOLD_FOR_RESET} consecutive errors")
    logger.info("Press Ctrl+C to stop")

    # Check Bluetooth adapter status on startup
    if not check_bluetooth_adapter():
        logger.warning("⚠ Bluetooth adapter not ready, attempting reset...")
        reset_bluetooth_adapter()

    # Start health check server
    start_health_server()

    # Initialize Home Assistant client if configured
    ha_client = None
    if HA_TOKEN:
        try:
            ha_client = HomeAssistantClient(HA_URL, HA_TOKEN)
            logger.info("✓ Home Assistant integration enabled")

            # Initialize all devices as "off" (not present) on startup
            for device in PHONE_MACS.keys():
                device_reported_states[device] = False
            update_home_assistant_states(ha_client)

        except Exception as e:
            logger.error(f"❌ Failed to initialize Home Assistant client: {e}")
            logger.info("Continuing without Home Assistant integration")
            health_status["ha_connected"] = False
    else:
        logger.warning("⚠ HA_TOKEN not set, running without Home Assistant integration")
        health_status["ha_connected"] = False

    # Update status to running
    health_status["status"] = "running"

    while True:
        try:
            # Check if we need to reset the Bluetooth adapter
            if consecutive_scan_failures >= ERROR_THRESHOLD_FOR_RESET:
                logger.warning(
                    f"⚠ {consecutive_scan_failures} consecutive scan failures detected"
                )
                if reset_bluetooth_adapter():
                    consecutive_scan_failures = 0
                    health_status["error_count"] = 0
                    # Wait a bit after reset before continuing
                    time.sleep(5)

            # Detect currently available devices
            detected_devices = devices_available()

            if detected_devices:
                logger.info(f"📍 Detected devices: {detected_devices}")
            else:
                logger.debug("🔍 No devices detected in current scan")

            # Update device tracking with timeout logic
            devices_arrived, devices_left = update_device_tracking(detected_devices)

            # Handle any state changes
            if devices_arrived or devices_left:
                if ha_client:
                    handle_state_changes(ha_client, devices_arrived, devices_left)
            else:
                # Even if no state changes, update HA periodically to keep entities fresh
                if ha_client:
                    update_home_assistant_states(ha_client)

            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            logger.info("🛑 Stopped by user")
            health_status["status"] = "stopping"

            # Set all devices as "off" before exiting
            if ha_client:
                logger.info("Setting all devices as away before exit...")
                for device in PHONE_MACS.keys():
                    device_reported_states[device] = False
                update_home_assistant_states(ha_client)

            break
        except Exception as e:
            logger.error(f"❌ Unexpected error in main loop: {e}")
            health_status["error_count"] += 1
            consecutive_scan_failures += 1
            time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()