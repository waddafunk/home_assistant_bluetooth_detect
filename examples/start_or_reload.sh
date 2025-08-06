#!/bin/bash

# Simple start/reload script for bluetooth-detection service

SERVICE_NAME="bluetooth-detection-home-assistant"

# Check if running with sudo
if [ "$EUID" -ne 0 ]; then 
    echo "Please run with sudo"
    exit 1
fi

# Reload systemd daemon
systemctl daemon-reload

# Restart the service (starts if stopped, restarts if running)
systemctl restart "$SERVICE_NAME"

# Wait a moment for service to stabilize
sleep 2

# Check if running
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "✓ Service running"
    # Show last 5 log lines to confirm it's working
    journalctl -u "$SERVICE_NAME" -n 5 --no-pager
else
    echo "✗ Service failed to start"
    # Show error logs
    journalctl -u "$SERVICE_NAME" -n 10 --no-pager
    exit 1
fi