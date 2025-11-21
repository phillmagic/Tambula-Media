#!/bin/bash
# Digital Signage Client Setup Script
# This script installs and configures the signage client on Raspberry Pi

set -e

echo "=================================="
echo "Digital Signage Client Setup"
echo "=================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
  echo "Please run as root (use sudo)"
  exit 1
fi

# Parse arguments
SUPABASE_URL="$1"
SUPABASE_ANON_KEY="$2"
GROUP_ID="$3"
DEVICE_NAME="$4"
DEVICE_TYPE="$5"

if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_ANON_KEY" ] || [ -z "$GROUP_ID" ] || [ -z "$DEVICE_NAME" ] || [ -z "$DEVICE_TYPE" ]; then
  echo "Usage: $0 <SUPABASE_URL> <SUPABASE_ANON_KEY> <GROUP_ID> <DEVICE_NAME> <DEVICE_TYPE>"
  exit 1
fi

echo "Device Type: $DEVICE_TYPE"
echo "Device Name: $DEVICE_NAME"
echo "Group ID: $GROUP_ID"
echo ""

echo "Installing dependencies..."
apt-get update
apt-get install -y python3 python3-pip vlc syncthing python3-full python3-venv

echo "Creating signage directory..."
mkdir -p /home/pi/signage
cd /home/pi/signage

echo "Creating Python virtual environment..."
python3 -m venv signage-env
source signage-env/bin/activate

echo "Installing Python packages in virtual environment..."
./signage-env/bin/pip install requests python-dotenv

echo "Downloading signage client..."
if [ "$DEVICE_TYPE" = "server" ]; then
  cat > signage-server.py << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
import os
import time
import requests
import subprocess
import json
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_ANON_KEY')
GROUP_ID = os.getenv('GROUP_ID')
DEVICE_NAME = os.getenv('DEVICE_NAME')
DEVICE_TYPE = os.getenv('DEVICE_TYPE')
VIDEO_DIR = os.getenv('VIDEO_DIR', './videos')
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '60'))

def register_device():
    """Register this device with the server"""
    device_id = subprocess.check_output(['cat', '/sys/class/net/eth0/address']).decode().strip()
    if not device_id:
        device_id = subprocess.check_output(['cat', '/sys/class/net/wlan0/address']).decode().strip()
    
    payload = {
        'device_id': device_id,
        'device_name': DEVICE_NAME,
        'device_type': DEVICE_TYPE,
        'group_id': GROUP_ID,
        'status': 'online'
    }
    
    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/devices",
        headers={
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json',
            'Prefer': 'return=representation'
        },
        json=payload
    )
    
    if response.status_code == 201:
        print(f"Device registered successfully: {DEVICE_NAME}")
        return response.json()[0]['id']
    elif response.status_code == 409:
        print(f"Device already registered: {DEVICE_NAME}")
        return device_id
    else:
        print(f"Failed to register device: {response.status_code} - {response.text}")
        return None

def check_for_updates():
    """Check for new content and download if available"""
    print("Checking for new content...")
    # Server devices download content from cloud storage
    # This would be implemented based on your storage solution
    pass

def main():
    print(f"Starting signage server: {DEVICE_NAME}")
    device_uuid = register_device()
    
    if not device_uuid:
        print("Failed to register device, exiting...")
        return
    
    while True:
        try:
            check_for_updates()
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
PYTHON_SCRIPT
  CLIENT_SCRIPT="signage-server.py"
else
  cat > signage-client.py << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
import os
import time
import requests
import subprocess
import json
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_ANON_KEY')
GROUP_ID = os.getenv('GROUP_ID')
DEVICE_NAME = os.getenv('DEVICE_NAME')
DEVICE_TYPE = os.getenv('DEVICE_TYPE')
VIDEO_DIR = os.getenv('VIDEO_DIR', './videos')
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '60'))

def register_device():
    """Register this device with the server"""
    device_id = subprocess.check_output(['cat', '/sys/class/net/eth0/address']).decode().strip()
    if not device_id:
        device_id = subprocess.check_output(['cat', '/sys/class/net/wlan0/address']).decode().strip()
    
    payload = {
        'device_id': device_id,
        'device_name': DEVICE_NAME,
        'device_type': DEVICE_TYPE,
        'group_id': GROUP_ID,
        'status': 'online'
    }
    
    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/devices",
        headers={
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json',
            'Prefer': 'return=representation'
        },
        json=payload
    )
    
    if response.status_code == 201:
        print(f"Device registered successfully: {DEVICE_NAME}")
        return response.json()[0]['id']
    elif response.status_code == 409:
        print(f"Device already registered: {DEVICE_NAME}")
        return device_id
    else:
        print(f"Failed to register device: {response.status_code} - {response.text}")
        return None

def play_video(video_path):
    """Play a video using VLC"""
    try:
        # Kill any existing VLC processes
        subprocess.run(['pkill', 'vlc'], capture_output=True)
        
        # Play video in fullscreen, looped
        cmd = [
            'cvlc',
            '--fullscreen',
            '--no-video-title-show',
            '--quiet',
            '--loop',
            video_path
        ]
        subprocess.Popen(cmd)
        print(f"Playing video: {video_path}")
    except Exception as e:
        print(f"Error playing video: {e}")

def main():
    print(f"Starting signage client: {DEVICE_NAME}")
    device_uuid = register_device()
    
    if not device_uuid:
        print("Failed to register device, exiting...")
        return
    
    # Simple demo - play a test video if available
    test_video = f"{VIDEO_DIR}/test.mp4"
    if os.path.exists(test_video):
        play_video(test_video)
    
    while True:
        try:
            # Client devices would sync content from server devices
            # and play according to schedules
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
PYTHON_SCRIPT
  CLIENT_SCRIPT="signage-client.py"
fi

echo "Creating .env file..."
cat > .env << ENV_FILE
SUPABASE_URL=$SUPABASE_URL
SUPABASE_ANON_KEY=$SUPABASE_ANON_KEY
GROUP_ID=$GROUP_ID
DEVICE_NAME=$DEVICE_NAME
DEVICE_TYPE=$DEVICE_TYPE
VIDEO_DIR=./videos
CHECK_INTERVAL=60
ENV_FILE

echo "Setting permissions..."
chown -R pi:pi /home/pi/signage
chmod +x $CLIENT_SCRIPT

echo "Creating systemd service..."
if [ "$DEVICE_TYPE" = "server" ]; then
  SERVICE_NAME="signage-server"
else
  SERVICE_NAME="signage-client"
fi

cat > /etc/systemd/system/$SERVICE_NAME.service << SERVICE_FILE
[Unit]
Description=Digital Signage $DEVICE_TYPE
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/signage
ExecStart=/home/pi/signage/signage-env/bin/python /home/pi/signage/$CLIENT_SCRIPT
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE_FILE

echo "Enabling and starting service..."
systemctl daemon-reload
systemctl enable $SERVICE_NAME.service
systemctl start $SERVICE_NAME.service

echo ""
echo "=================================="
echo "Setup Complete!"
echo "=================================="
echo ""
echo "Device Type: $DEVICE_TYPE"
echo "Device Name: $DEVICE_NAME"
echo "Group ID: $GROUP_ID"
echo ""
echo "Service Status:"
systemctl status $SERVICE_NAME.service --no-pager
echo ""
echo "To view logs: journalctl -u $SERVICE_NAME -f"
echo "To restart: sudo systemctl restart $SERVICE_NAME"
echo ""