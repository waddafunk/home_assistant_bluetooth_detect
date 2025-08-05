#!/usr/bin/env python3
"""
Simple Bluetooth Detection Loop
Every 3 seconds: check if device is available, print yes/no
"""

import subprocess
import time
import logging
import os

from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG to see all messages
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Your phone's MAC address
PHONE_MAC = os.getenv("PHONE_MAC")


def is_device_available():
    """Check if device is available using l2ping"""
    try:
        logger.debug(f"Running: l2ping -c 1 -t 2 {PHONE_MAC}")
        result = subprocess.run(
            ["l2ping", "-c", "1", "-t", "2", PHONE_MAC],
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
            logger.info("Device responded to l2ping!")
            return True
        else:
            logger.debug("Device did not respond to l2ping")
            return False

    except subprocess.TimeoutExpired:
        logger.warning("l2ping timed out")
        return False
    except FileNotFoundError:
        logger.error("l2ping command not found")
        return False
    except Exception as e:
        logger.error(f"Error running l2ping: {e}")
        return False


def main():
    logger.info(f"Checking device {PHONE_MAC} every 3 seconds...")
    logger.info("Press Ctrl+C to stop")

    while True:
        try:
            if is_device_available():
                print("YES")
            else:
                print("NO")

            time.sleep(3)

        except KeyboardInterrupt:
            logger.info("Stopped by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()
