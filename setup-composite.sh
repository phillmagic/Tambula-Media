#!/bin/bash
# Composite AV Setup for Tambula Signage Pi Devices
# Configures: composite video output, analog audio, ALSA, Chromium audio flags
# Supports Pi 3 and Pi 4 -- Pi 5 has no composite output
# Run as: sudo bash setup-composite.sh

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
step()  { echo -e "\n${CYAN}>>> $1${NC}"; }

[ "$(id -u)" -ne 0 ] && error "Run with sudo: sudo bash $0"

# =============================================================================
# DETECT HARDWARE AND OS
# =============================================================================
PI_MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo "Unknown")
info "Detected: $PI_MODEL"

if echo "$PI_MODEL" | grep -q "Pi 5"; then
  error "Raspberry Pi 5 has no composite output. Use HDMI instead."
fi

IS_PI4=false
IS_PI3=false
if echo "$PI_MODEL" | grep -q "Pi 4"; then
  IS_PI4=true
elif echo "$PI_MODEL" | grep -qE "Pi 3|Pi 2|Pi 1|Pi Zero"; then
  IS_PI3=true
else
  warn "Could not identify Pi model precisely -- applying Pi 3 settings"
  IS_PI3=true
fi

# Detect Pi OS version -- fkms overlay was removed in Bookworm (v12)
OS_ID=$(grep VERSION_ID /etc/os-release 2>/dev/null | cut -d'"' -f2 || echo "0")
IS_BOOKWORM=false
[ "$OS_ID" -ge 12 ] 2>/dev/null && IS_BOOKWORM=true

# Confirm fkms overlay actually exists on this install
USE_FKMS=false
for OPATH in /boot/overlays /boot/firmware/overlays; do
  [ -f "${OPATH}/vc4-fkms-v3d.dtbo" ] && USE_FKMS=true && break
done
$IS_BOOKWORM && USE_FKMS=false

info "Pi 4: $IS_PI4 | Pi 3: $IS_PI3 | Bookworm: $IS_BOOKWORM | fkms available: $USE_FKMS"

# Detect boot config path
if [ -f /boot/firmware/config.txt ]; then
  CONFIG=/boot/firmware/config.txt
elif [ -f /boot/config.txt ]; then
  CONFIG=/boot/config.txt
else
  error "Cannot find config.txt"
fi
info "Boot config: $CONFIG"

# Backup
cp "$CONFIG" "${CONFIG}.bak.$(date +%Y%m%d%H%M%S)"
info "Config backed up"

# =============================================================================
# HELPERS
# =============================================================================
set_config() {
  local key="$1" val="$2"
  if grep -qE "^#?${key}" "$CONFIG"; then
    sed -i "s|^#\?${key}.*|${key}=${val}|" "$CONFIG"
  else
    echo "${key}=${val}" >> "$CONFIG"
  fi
  info "Set ${key}=${val}"
}
comment_out() { sed -i "s|^${1}|#${1}|" "$CONFIG"; }
remove_line()  { sed -i "/${1}/d" "$CONFIG"; }

# =============================================================================
# 1. VIDEO -- COMPOSITE OUTPUT
# =============================================================================
step "1/5  Composite video output"

# Graphics driver
if $USE_FKMS; then
  if grep -q "dtoverlay=vc4-kms-v3d" "$CONFIG"; then
    sed -i 's|dtoverlay=vc4-kms-v3d.*|dtoverlay=vc4-fkms-v3d|g' "$CONFIG"
    info "Switched to vc4-fkms-v3d (better composite on Bullseye)"
  elif ! grep -q "dtoverlay=vc4-fkms-v3d" "$CONFIG"; then
    echo "dtoverlay=vc4-fkms-v3d" >> "$CONFIG"
    info "Added vc4-fkms-v3d"
  fi
else
  # Bookworm: revert any accidental fkms, keep kms
  if grep -q "dtoverlay=vc4-fkms-v3d" "$CONFIG"; then
    sed -i 's|dtoverlay=vc4-fkms-v3d|dtoverlay=vc4-kms-v3d|g' "$CONFIG"
    warn "Reverted fkms -> kms (fkms not available on Bookworm)"
  else
    info "Keeping vc4-kms-v3d (correct for Bookworm)"
  fi
fi

# Pi 4: enable composite (disabled by default) + lock framebuffer to PAL
if $IS_PI4; then
  set_config "enable_tvout" "1"
fi

# Both: lock framebuffer to PAL 720x576
# Prevents KMS driver jumping to 1920x1080 after boot splash (cuts screen off)
set_config "framebuffer_width"  "720"
set_config "framebuffer_height" "576"

# Suppress HDMI so composite is always used
remove_line "hdmi_force_hotplug"
set_config "hdmi_ignore_hotplug" "1"

# TV standard: PAL for Uganda/East Africa (change to 0 for NTSC regions)
set_config "sdtv_mode"   "2"
set_config "sdtv_aspect" "3"   # 16:9 for modern widescreen TVs (use 1 for old 4:3)

set_config "disable_overscan" "1"

# Clear HDMI mode overrides
comment_out "hdmi_group="
comment_out "hdmi_mode="
info "Video config done"

# =============================================================================
# 2. AUDIO -- ENABLE BCM2835 ONBOARD AUDIO
# =============================================================================
step "2/5  Enabling onboard audio"

set_config "dtparam" "audio=on"

# Remove HDMI audio lines added by setup.sh (wrong for composite)
remove_line "hdmi_drive="
remove_line "config_hdmi_boost="
remove_line "Tambula Signage - Force HDMI audio"
info "HDMI audio overrides removed"

# Ensure BCM2835 module loads on boot
if ! grep -q "snd_bcm2835" /etc/modules; then
  echo "snd_bcm2835" >> /etc/modules
  info "Added snd_bcm2835 to /etc/modules"
else
  info "snd_bcm2835 already in /etc/modules"
fi

# =============================================================================
# 3. ALSA -- SET ANALOG AS DEFAULT AUDIO DEVICE
# =============================================================================
step "3/5  Configuring ALSA default audio device"

cat > /etc/asound.conf << 'ALSA'
# Tambula Signage -- analog 3.5mm output (BCM2835 card 0)
#
# 'amp' is a named softvol device Chromium uses directly via --alsa-output-device=amp
# This avoids two pitfalls:
#   plughw:0,0  -- bypasses softvol entirely (no boost)
#   default     -- Chromium doesn't reliably open named defaults
pcm.amp {
    type plug
    slave.pcm {
        type softvol
        slave.pcm "hw:0,0"
        control {
            name "PCM Boost"
            card 0
        }
        max_dB 20.0
    }
}
pcm.!default {
    type plug
    slave.pcm "amp"
}
ctl.!default {
    type hw
    card 0
}
ALSA
info "ALSA configured: pcm.amp (softvol +20dB) -> hw:0,0"

# Max out hardware PCM volume
amixer -c 0 sset PCM 100% 2>/dev/null || true

# Open 'amp' once so softvol creates its control, then set it to 100%
aplay -D amp /dev/null 2>/dev/null || true
amixer sset 'PCM Boost' 100% 2>/dev/null || true
alsactl store 2>/dev/null || true

# =============================================================================
# 4. KIOSK SCRIPT -- ADD ALSA FLAGS TO CHROMIUM
# =============================================================================
step "4/5  Patching Chromium kiosk script for analog audio"

KIOSK_SCRIPT="/home/pi/signage/start-signage-kiosk.sh"

if [ ! -f "$KIOSK_SCRIPT" ]; then
  warn "Kiosk script not found at $KIOSK_SCRIPT -- skipping Chromium patch"
  warn "After setup.sh installs the signage, re-run this script to apply the Chromium audio fix"
else
  # Add ALSA env vars before the Chromium launch if not already there
  if ! grep -q "ALSA_CARD" "$KIOSK_SCRIPT"; then
    sed -i 's|echo "$(date): Launching Chromium..."|export ALSA_CARD=0\nexport ALSA_DEFAULT_CARD=0\necho "$(date): Launching Chromium..."|' "$KIOSK_SCRIPT"
    info "Added ALSA_CARD env vars to kiosk script"
  else
    info "ALSA_CARD already set in kiosk script"
  fi

  # Point Chromium at the named 'amp' PCM device from asound.conf
  # 'amp' = plug -> softvol (+20dB) -> hw:0,0
  if ! grep -q "alsa-output-device" "$KIOSK_SCRIPT"; then
    sed -i 's|--autoplay-policy=no-user-gesture-required|--autoplay-policy=no-user-gesture-required \\\n    --alsa-output-device=amp|' "$KIOSK_SCRIPT"
    info "Added --alsa-output-device=amp to Chromium flags"
  else
    sed -i 's|--alsa-output-device=[^ ]*|--alsa-output-device=amp|' "$KIOSK_SCRIPT"
    info "--alsa-output-device updated to amp (plug -> softvol -> hw:0,0)"
  fi

  # Fix window size for composite display (720x576, not 1920x1080)
  if grep -q "window-size=1920,1080" "$KIOSK_SCRIPT"; then
    sed -i 's|--window-size=1920,1080|--window-size=720,576|' "$KIOSK_SCRIPT"
    info "Fixed Chromium window size to 720x576 (composite resolution)"
  fi

  info "Kiosk script patched"
fi

# =============================================================================
# 5. GPU MEMORY
# =============================================================================
step "5/5  Setting GPU memory"
set_config "gpu_mem" "128"

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo "------------------------------------------------------"
echo "Final config snapshot:"
grep -E "vc4|hdmi|enable_tvout|sdtv|framebuffer|gpu_mem|overscan|dtparam=audio" "$CONFIG" | grep -v "^#" || true
echo "------------------------------------------------------"
echo ""
echo "Setup complete. Notes:"
echo ""
echo "  Cable: use a 4-pole TRRS cable (Nokia/iPod AV style)"
echo "         Tip=Left Audio | Ring1=Right Audio | Ring2=Video | Sleeve=GND"
echo ""
echo "  TV aspect: if image looks stretched/squished, adjust the TV's"
echo "             own Picture Size / Aspect Ratio menu (not the Pi)"
echo ""
echo "  sdtv_mode=2 (PAL) is set -- change to 0 for NTSC regions"
echo "  sdtv_aspect=3 (16:9) is set -- change to 1 for old 4:3 TVs"
echo ""
if $IS_PI3; then
  echo "  Pi 3: if video freezes after reboot check temp: vcgencmd measure_temp"
  echo "         throttles at 85C -- add heatsink for bus installs"
  echo ""
fi

read -rp "Reboot now? [y/N]: " REBOOT
if [[ "$REBOOT" =~ ^[Yy]$ ]]; then
  echo "Rebooting..."
  reboot
else
  echo "Reboot when ready to apply all changes."
fi
