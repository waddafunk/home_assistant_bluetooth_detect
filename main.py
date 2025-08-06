#!/usr/bin/env python3
"""
Simple Bluetooth Detection Loop
Every 3 seconds: check if device is available, print yes/no
"""

import subprocess
import time
import logging
import os
import json

from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG to see all messages
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Your phone's MAC address
PHONE_MACS = json.loads(os.getenv("PHONE_MACS"))


def devices_available():
    """Check if device is available using l2ping"""
    devices_found = []
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
            else:
                logger.debug("Device did not respond to l2ping")

        except subprocess.TimeoutExpired:
            logger.warning("l2ping timed out")
        except FileNotFoundError:
            logger.error("l2ping command not found")
        except Exception as e:
            logger.error(f"Error running l2ping: {e}")

    return devices_found


def main():
    logger.info(f"Checking devices {PHONE_MACS} every 3 seconds...")
    logger.info("Press Ctrl+C to stop")

    while True:
        try:
            devices_nearby = devices_available()
            if devices_nearby:
                print(f"Found {devices_nearby}")
            else:
                print("No devices found nearby")

            time.sleep(3)

        except KeyboardInterrupt:
            logger.info("Stopped by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()
