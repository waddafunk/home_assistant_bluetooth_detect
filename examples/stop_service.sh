#!/bin/bash

# Quick stop script for bluetooth-detection service

SERVICE_NAME="bluetooth-detection-home-assistant"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if running with sudo
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}[✗]${NC} Please run with sudo"
    echo "Usage: sudo $0"
    exit 1
fi

echo -e "${YELLOW}[!]${NC} Stopping $SERVICE_NAME service..."

# Check if service is running
if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    echo -e "${YELLOW}[!]${NC} Service is not running"
    exit 0
fi

# Stop the service
systemctl stop "$SERVICE_NAME"
sleep 1

# Verify it stopped
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo -e "${RED}[✗]${NC} Failed to stop service"
    echo "Trying to force kill..."
    systemctl kill "$SERVICE_NAME"
    sleep 1
    
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo -e "${RED}[✗]${NC} Service still running. Manual intervention required."
        echo "Try: sudo systemctl kill -s KILL $SERVICE_NAME"
        exit 1
    fi
fi

echo -e "${GREEN}[✓]${NC} Service stopped successfully"

# Show last few log entries
echo
echo "Last log entries:"
journalctl -u "$SERVICE_NAME" -n 5 --no-pager

# Optionally check if any bluetooth processes are still running
if pgrep -f "bluetooth_detection.py" > /dev/null; then
    echo
    echo -e "${YELLOW}[!]${NC} Warning: bluetooth_detection.py process still found"
    echo "PIDs:"
    pgrep -f "bluetooth_detection.py"
    echo
    read -p "Kill these processes? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pkill -f "bluetooth_detection.py"
        echo -e "${GREEN}[✓]${NC} Processes killed"
    fi
fi