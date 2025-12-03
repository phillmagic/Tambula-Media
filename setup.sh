#!/bin/bash
# Tambula Digital Signage - One-Command Installer
# Usage: curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s "SUPABASE_URL" "ANON_KEY" "GROUP_ID" "DEVICE_NAME" "TYPE"
# Example: curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s "https://xxx.supabase.co" "eyJ..." "de43..." "UBE575L" "client"

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_header() {
    echo ""
    echo -e "${BLUE}=========================================="
    echo -e "  $1"
    echo -e "==========================================${NC}"
    echo ""
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    print_error "Please run with sudo"
    echo "Usage: curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \"SUPABASE_URL\" \"ANON_KEY\" \"GROUP_ID\" \"DEVICE_NAME\" \"TYPE\""
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER="${SUDO_USER:-$USER}"
ACTUAL_HOME=$(getent passwd "$ACTUAL_USER" | cut -d: -f6)

print_header "TAMBULA DIGITAL SIGNAGE INSTALLER"

# Parse arguments
SUPABASE_URL="$1"
SUPABASE_ANON_KEY="$2"
GROUP_ID="$3"
DEVICE_NAME="$4"
INSTALL_TYPE="$5"  # "client" or "server"

# Validate arguments
if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_ANON_KEY" ] || [ -z "$GROUP_ID" ] || [ -z "$DEVICE_NAME" ] || [ -z "$INSTALL_TYPE" ]; then
    print_error "Missing required arguments"
    echo ""
    echo "Usage:"
    echo "  CLIENT: curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \"SUPABASE_URL\" \"ANON_KEY\" \"GROUP_ID\" \"DEVICE_NAME\" \"client\""
    echo "  SERVER: curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \"SUPABASE_URL\" \"ANON_KEY\" \"GROUP_ID\" \"SERVER_NAME\" \"server\""
    echo ""
    echo "Example:"
    echo "  curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \"https://xxx.supabase.co\" \"eyJ...\" \"de43...\" \"UBE575L\" \"client\""
    exit 1
fi

# Validate install type
if [ "$INSTALL_TYPE" != "client" ] && [ "$INSTALL_TYPE" != "server" ]; then
    print_error "Install type must be 'client' or 'server'"
    exit 1
fi

print_info "Install Type: $INSTALL_TYPE"
print_info "Device Name: $DEVICE_NAME"
print_info "User: $ACTUAL_USER"
print_info "Home: $ACTUAL_HOME"

# Get hardware ID
print_info "Detecting hardware ID..."
DEVICE_ID=""
if [ -f /sys/class/net/eth0/address ]; then
    DEVICE_ID=$(cat /sys/class/net/eth0/address | tr -d ':')
elif [ -f /sys/class/net/wlan0/address ]; then
    DEVICE_ID=$(cat /sys/class/net/wlan0/address | tr -d ':')
else
    # Fallback to serial
    DEVICE_ID=$(cat /proc/cpuinfo | grep Serial | cut -d ' ' -f 2)
fi
print_success "Device ID: $DEVICE_ID"

# Determine installation directory
if [ "$INSTALL_TYPE" = "client" ]; then
    INSTALL_DIR="$ACTUAL_HOME/signage"
    GITHUB_SCRIPT="signage-client-analytics.py"
    SERVICE_NAME="tambula-signage"
else
    INSTALL_DIR="$ACTUAL_HOME/park-server"
    GITHUB_SCRIPT="park-server-new.py"
    SERVICE_NAME="tambula-park-server"
fi

print_header "SYSTEM UPDATE"
print_info "Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq
print_success "System updated"

print_header "INSTALLING DEPENDENCIES"

# Detect if we're on Desktop or Lite
print_info "Detecting Raspberry Pi OS variant..."
if dpkg -l | grep -q raspberrypi-ui-mods; then
    OS_VARIANT="Desktop"
    print_success "Detected: Raspberry Pi OS Desktop"
else
    OS_VARIANT="Lite"
    print_success "Detected: Raspberry Pi OS Lite"
fi

# Common dependencies
print_info "Installing Python and common tools..."
apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git

# Client-specific packages
if [ "$INSTALL_TYPE" = "client" ]; then
    print_info "Installing client dependencies..."
    
    # Install X11 if on Lite (Desktop already has it)
    if [ "$OS_VARIANT" = "Lite" ]; then
        print_info "Installing minimal X11 for Pi OS Lite..."
        apt-get install --no-install-recommends -y -qq \
            xserver-xorg \
            x11-xserver-utils \
            xinit \
            xterm
        print_success "X11 server installed"
    fi
    
    # Install Chromium
    print_info "Installing Chromium..."
    if apt-cache show chromium &> /dev/null; then
        apt-get install -y -qq chromium
    elif apt-cache show chromium-browser &> /dev/null; then
        apt-get install -y -qq chromium-browser
    else
        print_warning "Chromium not found in apt, may need manual installation"
    fi
    
    # Install kiosk utilities
    apt-get install -y -qq \
        unclutter \
        xdotool \
        x11-xserver-utils
    
    print_success "Client dependencies installed"
else
    # Server doesn't need X11 or Chromium
    print_info "Server mode - skipping GUI packages"
fi

print_success "Dependencies installed"

print_header "CREATING DIRECTORY STRUCTURE"
print_info "Creating $INSTALL_DIR..."

# Create as actual user, not root
sudo -u "$ACTUAL_USER" mkdir -p "$INSTALL_DIR"/{videos,assets,cache,logs}
print_success "Directory structure created"

print_header "DOWNLOADING APPLICATION FILES"

# Download main script
print_info "Downloading $GITHUB_SCRIPT..."
SCRIPT_URL="https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/$GITHUB_SCRIPT"

if [ "$INSTALL_TYPE" = "client" ]; then
    DEST_FILE="$INSTALL_DIR/signage-client.py"
else
    DEST_FILE="$INSTALL_DIR/park-server.py"
fi

curl -sSL "$SCRIPT_URL" -o "$DEST_FILE"
chown "$ACTUAL_USER:$ACTUAL_USER" "$DEST_FILE"
chmod +x "$DEST_FILE"
print_success "Downloaded $GITHUB_SCRIPT"

# Install Python dependencies
print_info "Installing Python dependencies..."
sudo -u "$ACTUAL_USER" python3 -m venv "$INSTALL_DIR/venv"
sudo -u "$ACTUAL_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u "$ACTUAL_USER" "$INSTALL_DIR/venv/bin/pip" install requests python-dotenv -q
print_success "Python dependencies installed"

print_header "CONFIGURATION"

# Prompt for Park Server IP (client only)
if [ "$INSTALL_TYPE" = "client" ]; then
    echo ""
    print_info "Enter Park Server IP address (press Enter to skip for Supabase-only mode):"
    read -p "Park Server IP: " PARK_SERVER_IP
    
    if [ -n "$PARK_SERVER_IP" ]; then
        read -p "Park Server Port [8080]: " PARK_SERVER_PORT
        PARK_SERVER_PORT="${PARK_SERVER_PORT:-8080}"
        print_success "Park Server: $PARK_SERVER_IP:$PARK_SERVER_PORT"
    else
        PARK_SERVER_IP=""
        PARK_SERVER_PORT=""
        print_warning "No park server configured (Supabase-only mode)"
    fi
fi

# Create .env file
print_info "Creating .env file..."

if [ "$INSTALL_TYPE" = "client" ]; then
    # Client .env
    cat > "$INSTALL_DIR/.env" << EOF
# Tambula Digital Signage Client Configuration
# Generated: $(date)

# Supabase Configuration
SUPABASE_URL=$SUPABASE_URL
SUPABASE_ANON_KEY=$SUPABASE_ANON_KEY
GROUP_ID=$GROUP_ID

# Device Information
DEVICE_NAME=$DEVICE_NAME
DEVICE_ID=$DEVICE_ID

# Directories
VIDEO_DIR=$INSTALL_DIR/videos

# Refresh Intervals
CHECK_INTERVAL=60

# Park Server Configuration (Optional)
EOF

    if [ -n "$PARK_SERVER_IP" ]; then
        cat >> "$INSTALL_DIR/.env" << EOF
PARK_SERVER_IP=$PARK_SERVER_IP
PARK_SERVER_PORT=$PARK_SERVER_PORT
SYNC_INTERVAL=60
EOF
    else
        cat >> "$INSTALL_DIR/.env" << EOF
# PARK_SERVER_IP=
# PARK_SERVER_PORT=8080
# SYNC_INTERVAL=60
EOF
    fi

else
    # Server .env
    cat > "$INSTALL_DIR/.env" << EOF
# Tambula Park Server Configuration
# Generated: $(date)

# Supabase Configuration
SUPABASE_URL=$SUPABASE_URL
SUPABASE_ANON_KEY=$SUPABASE_ANON_KEY
GROUP_ID=$GROUP_ID

# Server Configuration
SERVER_NAME=$DEVICE_NAME
SERVER_PORT=8080
SYNC_INTERVAL=600

# Optional: Service Role Key for Analytics
# SUPABASE_SERVICE_ROLE_KEY=
EOF
fi

chown "$ACTUAL_USER:$ACTUAL_USER" "$INSTALL_DIR/.env"
print_success ".env file created"

print_header "SETTING UP SYSTEMD SERVICE"

# Create systemd service
if [ "$INSTALL_TYPE" = "client" ]; then
    cat > "/etc/systemd/system/$SERVICE_NAME.service" << EOF
[Unit]
Description=Tambula Digital Signage Client
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$ACTUAL_USER
Group=$ACTUAL_USER
WorkingDirectory=$INSTALL_DIR
Environment="PATH=/usr/bin:/usr/local/bin:$INSTALL_DIR/venv/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/signage-client.py
Restart=always
RestartSec=10
StandardOutput=append:$INSTALL_DIR/logs/signage.log
StandardError=append:$INSTALL_DIR/logs/signage-error.log

NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

else
    cat > "/etc/systemd/system/$SERVICE_NAME.service" << EOF
[Unit]
Description=Tambula Park Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$ACTUAL_USER
Group=$ACTUAL_USER
WorkingDirectory=$INSTALL_DIR
Environment="PATH=/usr/bin:/usr/local/bin:$INSTALL_DIR/venv/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/park-server.py
Restart=always
RestartSec=10
StandardOutput=append:$INSTALL_DIR/logs/park-server.log
StandardError=append:$INSTALL_DIR/logs/park-server-error.log

NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
fi

systemctl daemon-reload
systemctl enable "$SERVICE_NAME.service"
print_success "Systemd service created and enabled"

# Client-specific setup
if [ "$INSTALL_TYPE" = "client" ]; then
    print_header "SETTING UP KIOSK MODE"
    
    # Create kiosk startup script
    cat > "$INSTALL_DIR/start-signage-kiosk.sh" << 'EOFSCRIPT'
#!/bin/bash
# Tambula Digital Signage - Chromium Kiosk Startup

# Wait for server to be ready
echo "$(date): Waiting for signage server..." >> $HOME/signage/logs/kiosk.log
for i in {1..60}; do
    if curl -s http://localhost:8080/status > /dev/null 2>&1; then
        echo "$(date): Server is ready!" >> $HOME/signage/logs/kiosk.log
        break
    fi
    sleep 2
done

# Disable screen blanking
xset s off
xset -dpms
xset s noblank

# Hide cursor
unclutter -idle 3 &

# Detect chromium
if command -v chromium &> /dev/null; then
    CHROMIUM_CMD="chromium"
elif command -v chromium-browser &> /dev/null; then
    CHROMIUM_CMD="chromium-browser"
else
    echo "ERROR: Chromium not found!" >> $HOME/signage/logs/kiosk.log
    exit 1
fi

# Launch Chromium in kiosk mode
$CHROMIUM_CMD \
    --kiosk \
    --start-fullscreen \
    --noerrdialogs \
    --disable-infobars \
    --no-first-run \
    --disable-session-crashed-bubble \
    --disable-features=TranslateUI \
    --disable-component-update \
    --check-for-update-interval=31536000 \
    --overscroll-history-navigation=0 \
    --autoplay-policy=no-user-gesture-required \
    --password-store=basic \
    --use-mock-keychain \
    --app=http://localhost:8080 \
    >> $HOME/signage/logs/kiosk.log 2>&1 &

wait
EOFSCRIPT

    chown "$ACTUAL_USER:$ACTUAL_USER" "$INSTALL_DIR/start-signage-kiosk.sh"
    chmod +x "$INSTALL_DIR/start-signage-kiosk.sh"
    
    # Configure auto-start based on OS variant
    if [ "$OS_VARIANT" = "Desktop" ]; then
        print_info "Configuring Desktop autostart..."
        
        # Create desktop autostart
        AUTOSTART_DIR="$ACTUAL_HOME/.config/autostart"
        sudo -u "$ACTUAL_USER" mkdir -p "$AUTOSTART_DIR"
        
        cat > "$AUTOSTART_DIR/tambula-signage.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Tambula Signage Kiosk
Comment=Start Tambula Digital Signage in Kiosk Mode
Exec=$INSTALL_DIR/start-signage-kiosk.sh
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF
        
        chown "$ACTUAL_USER:$ACTUAL_USER" "$AUTOSTART_DIR/tambula-signage.desktop"
        print_success "Desktop autostart configured"
        
    else
        print_info "Configuring Pi OS Lite autostart..."
        
        # Create .xinitrc to start kiosk
        cat > "$ACTUAL_HOME/.xinitrc" << EOF
#!/bin/bash
# Tambula Signage - X11 startup
exec $INSTALL_DIR/start-signage-kiosk.sh
EOF
        chown "$ACTUAL_USER:$ACTUAL_USER" "$ACTUAL_HOME/.xinitrc"
        chmod +x "$ACTUAL_HOME/.xinitrc"
        
        # Configure .bash_profile to auto-start X on tty1
        if ! grep -q "startx" "$ACTUAL_HOME/.bash_profile" 2>/dev/null; then
            cat >> "$ACTUAL_HOME/.bash_profile" << 'EOF'

# Tambula Signage - Auto-start X11 on tty1
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    startx
fi
EOF
            chown "$ACTUAL_USER:$ACTUAL_USER" "$ACTUAL_HOME/.bash_profile"
        fi
        
        # Enable auto-login on console
        print_info "Enabling auto-login..."
        raspi-config nonint do_boot_behaviour B2 2>/dev/null || true
        
        print_success "Pi OS Lite autostart configured"
    fi
    
    print_success "Kiosk mode configured"
    
    # Configure HDMI audio
    print_info "Configuring HDMI audio..."
    if ! grep -q "hdmi_drive=2" /boot/config.txt; then
        echo "" >> /boot/config.txt
        echo "# Tambula Signage - Force HDMI audio" >> /boot/config.txt
        echo "hdmi_drive=2" >> /boot/config.txt
        echo "hdmi_force_hotplug=1" >> /boot/config.txt
        echo "config_hdmi_boost=4" >> /boot/config.txt
    fi
    print_success "HDMI audio configured"
    
    # Disable screen blanking
    print_info "Disabling screen blanking..."
    raspi-config nonint do_blanking 1 2>/dev/null || true
    print_success "Screen blanking disabled"
fi

print_header "STARTING SERVICE"
systemctl start "$SERVICE_NAME.service"
sleep 3

if systemctl is-active --quiet "$SERVICE_NAME.service"; then
    print_success "Service started successfully!"
else
    print_warning "Service may not have started correctly"
fi

print_header "INSTALLATION COMPLETE!"

echo ""
print_success "Tambula $INSTALL_TYPE installed successfully!"
echo ""

if [ "$INSTALL_TYPE" = "client" ]; then
    echo "📋 What was installed:"
    echo "   • Signage client: $INSTALL_DIR/signage-client.py"
    echo "   • Configuration: $INSTALL_DIR/.env"
    echo "   • Service: /etc/systemd/system/$SERVICE_NAME.service"
    echo "   • Kiosk script: $INSTALL_DIR/start-signage-kiosk.sh"
    echo "   • Desktop autostart: $AUTOSTART_DIR/tambula-signage.desktop"
    echo ""
    echo "🌐 Park Server Configuration:"
    if [ -n "$PARK_SERVER_IP" ]; then
        echo "   • IP: $PARK_SERVER_IP"
        echo "   • Port: $PARK_SERVER_PORT"
    else
        echo "   • Not configured (Supabase-only mode)"
        echo "   • To add later, edit: $INSTALL_DIR/.env"
    fi
else
    echo "📋 What was installed:"
    echo "   • Park server: $INSTALL_DIR/park-server.py"
    echo "   • Configuration: $INSTALL_DIR/.env"
    echo "   • Service: /etc/systemd/system/$SERVICE_NAME.service"
    echo ""
    echo "🌐 Server will be available at:"
    LOCAL_IP=$(hostname -I | awk '{print $1}')
    echo "   • http://$LOCAL_IP:8080"
    echo "   • http://localhost:8080"
fi

echo ""
echo "📊 Useful commands:"
echo "   • Check status:  sudo systemctl status $SERVICE_NAME"
echo "   • View logs:     tail -f $INSTALL_DIR/logs/*.log"
echo "   • Restart:       sudo systemctl restart $SERVICE_NAME"
echo "   • Stop:          sudo systemctl stop $SERVICE_NAME"
echo ""

if [ "$INSTALL_TYPE" = "client" ]; then
    echo "🚀 NEXT STEPS:"
    echo "   1. Reboot to test auto-start: sudo reboot"
    echo "   2. After reboot, kiosk should start automatically"
    echo "   3. Press F11 or ESC to exit fullscreen if needed"
    echo ""
    print_warning "Don't forget to configure Park Server IP if needed!"
else
    echo "🚀 NEXT STEPS:"
    echo "   1. Check service status: sudo systemctl status $SERVICE_NAME"
    echo "   2. Verify server is running: curl http://localhost:8080/status"
    echo "   3. Configure bus clients to connect to this server"
    echo ""
    print_warning "Optional: Add SUPABASE_SERVICE_ROLE_KEY to .env for analytics"
fi

echo ""
print_info "Installation log saved to: /var/log/tambula-install.log"
echo ""

# Save installation details
cat > "/var/log/tambula-install.log" << EOF
Tambula Digital Signage Installation
=====================================
Date: $(date)
Type: $INSTALL_TYPE
Device Name: $DEVICE_NAME
Device ID: $DEVICE_ID
Install Directory: $INSTALL_DIR
User: $ACTUAL_USER
Supabase URL: $SUPABASE_URL
Group ID: $GROUP_ID
EOF

if [ "$INSTALL_TYPE" = "client" ] && [ -n "$PARK_SERVER_IP" ]; then
    echo "Park Server: $PARK_SERVER_IP:$PARK_SERVER_PORT" >> "/var/log/tambula-install.log"
fi

print_success "Setup complete! 🎉"
