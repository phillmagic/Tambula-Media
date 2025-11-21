#!/bin/bash
# Digital Signage Setup Script - Updated for Cronjob Approach
# This script now uses the cronjob setup method for better reliability

set -e

echo "=== Digital Signage Setup ==="
echo "This script will set up your Raspberry Pi for digital signage"
echo "Using cronjob method for reliable startup"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run this script as root: sudo bash setup.sh"
    exit 1
fi

# Update and install system dependencies
echo "Updating system packages..."
apt-get update
apt-get install -y python3 python3-pip python3-venv git curl vlc

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found."
    echo "Please create .env file with your Supabase credentials first."
    echo "You can copy from .env.example and edit with your values."
    exit 1
fi

# Run the cronjob setup script
echo "Running cronjob setup..."
bash cronjob-setup.sh

echo ""
echo "=== Setup Complete ==="
echo "Your device is now configured to use cronjobs for reliable startup."
echo ""
echo "Next steps:"
echo "1. Reboot to test automatic startup: sudo reboot"
echo "2. Check logs in: $(pwd)/logs/"
echo "3. Verify device appears in the web interface"
echo ""
echo "For troubleshooting, see CRONJOB_SETUP_GUIDE.md"