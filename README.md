# Bluetooth Detection Service for Home Assistant

A Python service that monitors Bluetooth device presence and integrates with Home Assistant to track who's home. Uses L2 ping to detect phones and other Bluetooth devices, with configurable timeout periods to prevent false "away" notifications.

## Features

- **Reliable Bluetooth Detection**: Uses `l2ping` for active device detection
- **Timeout Protection**: Configurable delay before marking devices as "away" (default 5 minutes)
- **Home Assistant Integration**: Creates binary sensors and sends events
- **Group Sensors**: Tracks "everybody home", "nobody home", and "anybody home" status
- **Health Monitoring**: Built-in HTTP health check endpoint
- **Systemd Service**: Runs as a system service with automatic restart
- **Event Notifications**: Sends custom events for arrivals and departures

## Requirements

- Linux system with Bluetooth support (tested on Raspberry Pi)
- Python 3.7+
- `l2ping` utility (part of bluez-utils package)
- Home Assistant with REST API access
- Root privileges (required for L2 ping)

## Installation

### 1. Install System Dependencies

```bash
# Ubuntu/Debian/Raspberry Pi OS
sudo apt-get update
sudo apt-get install bluez bluez-tools python3-pip python3-venv

# Verify l2ping is available
which l2ping
```

### 2. Clone and Setup Project

```bash
# Clone to your preferred directory
git clone <your-repo> /home/pi/bluetooth-detection
cd /home/pi/bluetooth-detection

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install requests python-dotenv
```

### 3. Configure Environment

Create a `.env` file in the project directory:

```bash
# Application settings
APP_NAME="Bluetooth Home Detection"

# Device configuration - JSON format with device names and MAC addresses
PHONE_MACS={"John": "AA:BB:CC:DD:EE:FF", "Jane": "11:22:33:44:55:66"}

# Home Assistant configuration
HA_URL=http://192.168.1.100:8123
HA_TOKEN=your_long_lived_access_token_here

# Timeout before marking device as away (minutes)
AWAY_TIMEOUT=5

# Health check server (optional)
HEALTH_CHECK_ENABLED=true
HEALTH_PORT=8080
```

### 4. Get Home Assistant Long-Lived Access Token

1. In Home Assistant, go to your Profile (click your name in sidebar)
2. Scroll down to "Long-lived access tokens"
3. Click "Create Token"
4. Give it a name like "Bluetooth Detection"
5. Copy the token and add it to your `.env` file

### 5. Find Device MAC Addresses

```bash
# Scan for nearby Bluetooth devices
sudo hcitool scan

# Or use bluetoothctl
bluetoothctl
> scan on
> devices
> quit
```

## Service Installation

### 1. Install as Systemd Service

```bash
# Copy the service file and update paths
sudo cp service /etc/systemd/system/bluetooth-detection-home-assistant.service

# Edit the service file to match your paths
sudo nano /etc/systemd/system/bluetooth-detection-home-assistant.service
```

Update these lines in the service file:
```ini
WorkingDirectory=/home/pi/bluetooth-detection
ExecStart=/home/pi/bluetooth-detection/venv/bin/python /home/pi/bluetooth-detection/main.py
```

### 2. Enable and Start Service

```bash
# Reload systemd and start service
sudo systemctl daemon-reload
sudo systemctl enable bluetooth-detection-home-assistant
sudo systemctl start bluetooth-detection-home-assistant

# Check status
sudo systemctl status bluetooth-detection-home-assistant
```

## Usage

### Manual Testing

```bash
# Test the service manually
cd /home/pi/bluetooth-detection
source venv/bin/activate
sudo python main.py
```

### Using Helper Scripts

```bash
# Start or restart the service
sudo ./start_or_reload.sh

# Stop the service
sudo ./stop_service.sh
```

### Monitoring Logs

```bash
# Follow live logs
sudo journalctl -u bluetooth-detection-home-assistant -f

# View recent logs
sudo journalctl -u bluetooth-detection-home-assistant -n 50
```

### Health Check

Visit `http://your-pi-ip:8080/health` to see service status:

```json
{
  "healthy": true,
  "status": "running",
  "last_scan": "2025-01-15T10:30:45",
  "devices_found": ["John"],
  "error_count": 0,
  "ha_connected": true,
  "uptime_seconds": 3600
}
```

## Home Assistant Integration

The service automatically creates these entities in Home Assistant:

### Individual Device Sensors
- `binary_sensor.bluetooth_john` - John's presence
- `binary_sensor.bluetooth_jane` - Jane's presence

### Group Sensors
- `binary_sensor.bluetooth_everybody_home` - True when all devices are present
- `binary_sensor.bluetooth_nobody_home` - True when no devices are present  
- `binary_sensor.bluetooth_anybody_home` - True when at least one device is present

### Events
The service sends these events that you can use in automations:
- `bluetooth_device_arrived` - When a device is detected
- `bluetooth_device_left` - When a device times out
- `bluetooth_everybody_home` - When all family members are home
- `bluetooth_nobody_home` - When everyone has left
- `bluetooth_anybody_home` - When the first person arrives

## Monitoring (Optional)

### Add Health Check Sensor

Add this to your Home Assistant `configuration.yaml`:

```yaml
sensor:
  - platform: rest
    name: "Bluetooth Detection Service Health"
    resource: "http://192.168.1.50:8080/health"  # Replace with your Pi's IP
    value_template: "{{ 'Online' if value_json.healthy else 'Offline' }}"
    json_attributes:
      - status
      - last_scan
      - devices_found
      - error_count
      - uptime_seconds
    scan_interval: 30
```

### Create Alert Automation

Use the example in `monitoring_alert.yaml` to get notified if the service goes down.

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | "Home assistant bluetooth detector" | Service name for logs |
| `PHONE_MACS` | Required | JSON object of device names and MAC addresses |
| `HA_URL` | `http://localhost:8123` | Home Assistant URL |
| `HA_TOKEN` | Required | Long-lived access token |
| `AWAY_TIMEOUT` | `5` | Minutes to wait before marking device as away |
| `HEALTH_CHECK_ENABLED` | `true` | Enable health check HTTP server |
| `HEALTH_PORT` | `8080` | Port for health check server |

### Timeout Behavior

The service uses a configurable timeout to prevent false "away" notifications:

1. **Device Detected**: Immediately marked as "home"
2. **Device Not Detected**: Remains "home" for `AWAY_TIMEOUT` minutes
3. **Timeout Reached**: Marked as "away" and sends departure event

This prevents temporary Bluetooth disconnections from triggering false departures.

## Troubleshooting

### Common Issues

**Service won't start:**
```bash
# Check service status and logs
sudo systemctl status bluetooth-detection-home-assistant
sudo journalctl -u bluetooth-detection-home-assistant -n 20
```

**l2ping not found:**
```bash
# Install bluez utilities
sudo apt-get install bluez bluez-tools
```

**Permission denied:**
- L2 ping requires root privileges
- Ensure service runs as root user
- Check that user can access Bluetooth adapter

**Devices not detected:**
```bash
# Test l2ping manually
sudo l2ping -c 1 -t 2 AA:BB:CC:DD:EE:FF

# Check Bluetooth adapter status
hciconfig
sudo hciconfig hci0 up  # if adapter is down
```

**Home Assistant connection issues:**
- Verify HA_URL is correct and accessible
- Check that HA_TOKEN is valid
- Ensure Home Assistant allows REST API access

### Debug Mode

Enable debug logging by adding to your `.env`:
```bash
PYTHONPATH=/home/pi/bluetooth-detection
```

Then check logs for detailed l2ping output and state changes.

## How It Works

1. **Device Scanning**: Every 3 seconds, runs `l2ping` against configured MAC addresses
2. **State Tracking**: Maintains last-seen timestamps for each device
3. **Timeout Logic**: Only marks devices as "away" after the configured timeout period
4. **HA Integration**: Updates binary sensors and sends events on state changes
5. **Group Logic**: Calculates and updates group sensors based on individual device states

## Contributing

Feel free to submit issues and enhancement requests!

---

**Note**: This service requires root privileges due to L2 ping requirements. Consider the security implications in your environment.
