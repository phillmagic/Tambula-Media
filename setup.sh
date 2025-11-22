#!/bin/bash
# Digital Signage Setup Script - Production Version
# Updated for new clean server/client files with cronjob approach

set -e

echo "=== Digital Signage Setup (Production) ==="
echo "This script will set up your Raspberry Pi for digital signage"
echo "Using cronjob method for reliable startup (avoids systemd timing issues)"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run this script as root: sudo bash setup.sh"
    exit 1
fi

# Update and install system dependencies
echo "Updating system packages..."
apt-get update
apt-get install -y python3 python3-pip python3-venv git curl vlc

# Install Syncthing (required for file sharing)
echo "Installing Syncthing..."
apt-get install -y apt-transport-https
curl -s -o /usr/share/keyrings/syncthing-archive-keyring.gpg https://syncthing.net/release-key.gpg
echo "deb [signed-by=/usr/share/keyrings/syncthing-archive-keyring.gpg] https://apt.syncthing.net/ syncthing stable" > /etc/apt/sources.list.d/syncthing.list
apt-get update
apt-get install -y syncthing

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found."
    echo "Please create .env file with your Supabase credentials first."
    echo "You can copy from .env.example and edit with your values."
    echo ""
    echo "Required variables:"
    echo "- SUPABASE_URL"
    echo "- SUPABASE_ANON_KEY"
    echo "- GROUP_ID"
    echo "- DEVICE_NAME"
    echo "- SERVER_IP (for client devices only)"
    exit 1
fi

# Load environment variables to check device type
source .env

# Determine device type
echo ""
echo "Select device type:"
echo "1) Server Device (downloads and shares videos via Syncthing)"
echo "2) Client Device (receives videos from server and plays them)"
read -p "Enter choice (1 or 2): " device_choice

case $device_choice in
    1)
        DEVICE_TYPE="server"
        SCRIPT_NAME="signage-server.py"
        echo "Setting up as SERVER device..."
        ;;
    2)
        DEVICE_TYPE="client" 
        SCRIPT_NAME="signage-client.py"
        echo "Setting up as CLIENT device..."
        
        # Check if SERVER_IP is set for client
        if [ -z "$SERVER_IP" ]; then
            echo "Error: SERVER_IP must be set in .env file for client devices"
            echo "Add: SERVER_IP=192.168.1.xxx (your server's IP address)"
            exit 1
        fi
        ;;
    *)
        echo "Invalid choice. Exiting."
        exit 1
        ;;
esac

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv

# Install Python dependencies
echo "Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install requests python-dotenv

# Make the script executable
chmod +x "$SCRIPT_NAME"

# Create necessary directories
mkdir -p videos logs

# Remove any existing systemd services (clean up)
if systemctl is-active --quiet "signage-$DEVICE_TYPE" 2>/dev/null; then
    echo "Stopping existing systemd service..."
    systemctl stop "signage-$DEVICE_TYPE"
    systemctl disable "signage-$DEVICE_TYPE"
fi

if [ -f "/etc/systemd/system/signage-$DEVICE_TYPE.service" ]; then
    echo "Removing existing systemd service..."
    rm "/etc/systemd/system/signage-$DEVICE_TYPE.service"
    systemctl daemon-reload
fi

# Get absolute paths
SCRIPT_DIR=$(pwd)
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
MAIN_SCRIPT="$SCRIPT_DIR/$SCRIPT_NAME"

# Create a wrapper script for proper environment loading
echo "Creating wrapper script for reliable startup..."
cat > "run-$DEVICE_TYPE.sh" << EOF
#!/bin/bash
# Wrapper script for $DEVICE_TYPE device
cd $SCRIPT_DIR

# Wait for network to be ready (important for Pi startup)
echo "Waiting for network..."
for i in {1..30}; do
    if ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        echo "Network ready"
        break
    fi
    sleep 2
done

# Load environment and start
source venv/bin/activate
export \$(grep -v '^#' .env | xargs)
$VENV_PYTHON $MAIN_SCRIPT
EOF

chmod +x "run-$DEVICE_TYPE.sh"

# Set up cronjobs for pi user (not root)
echo "Setting up cronjobs for pi user..."

# Switch to pi user for crontab operations
sudo -u pi bash << EOF
# Remove any existing signage cronjobs
(crontab -l 2>/dev/null | grep -v "$SCRIPT_NAME" | grep -v "run-$DEVICE_TYPE.sh" | grep -v "signage") | crontab -

# Add startup cronjob (runs at boot)
STARTUP_CRON="@reboot sleep 30 && cd $SCRIPT_DIR && $SCRIPT_DIR/run-$DEVICE_TYPE.sh >> $SCRIPT_DIR/logs/$DEVICE_TYPE-startup.log 2>&1"
(crontab -l 2>/dev/null; echo "\$STARTUP_CRON") | crontab -

# Add health check cronjob (restarts if process dies)
HEALTH_CHECK_CRON="*/5 * * * * pgrep -f '$SCRIPT_NAME' > /dev/null || (cd $SCRIPT_DIR && $SCRIPT_DIR/run-$DEVICE_TYPE.sh >> $SCRIPT_DIR/logs/$DEVICE_TYPE-health.log 2>&1)"
(crontab -l 2>/dev/null; echo "\$HEALTH_CHECK_CRON") | crontab -

echo "Cronjobs configured for pi user:"
crontab -l | grep -E "(signage|run-$DEVICE_TYPE)"
EOF

echo ""
echo "=== Setup Complete ==="
echo "Device type: $DEVICE_TYPE"
echo "Main script: $SCRIPT_NAME"
echo "Wrapper script: run-$DEVICE_TYPE.sh"
echo ""
echo "Cronjobs configured:"
echo "- Startup: @reboot (with 30s delay for network)"
echo "- Health check: every 5 minutes"
echo ""
echo "To test immediately:"
echo "  sudo -u pi $SCRIPT_DIR/run-$DEVICE_TYPE.sh"
echo ""
echo "Next steps:"
echo "1. Reboot to test automatic startup: sudo reboot"
echo "2. Check logs in: $SCRIPT_DIR/logs/"
echo "3. Verify device appears in web interface"

if [ "$DEVICE_TYPE" = "server" ]; then
    echo "4. Syncthing UI will be available at: http://[pi-ip]:8384"
    echo "5. Configure client devices to connect to this server"
elif [ "$DEVICE_TYPE" = "client" ]; then
    echo "4. Syncthing UI available at: http://[pi-ip]:8384"
    echo "5. Add server device ($SERVER_IP) in Syncthing web interface"
    echo "6. Accept shared 'videos' folder from server"
fi

echo ""
echo "The device will automatically start on boot via cronjob."
echo "This avoids systemd timing issues with network/hardware readiness."