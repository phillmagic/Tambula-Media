#!/bin/bash
# RTC Setup Script for Raspberry Pi (Signage Devices)
# Supports DS3231 (default), DS1307, PCF8523
# Run as: sudo bash setup-rtc.sh

set -e

# â”€â”€ Colours â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# â”€â”€ Root check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
[ "$(id -u)" -ne 0 ] && error "Run this script with sudo: sudo bash $0"

# â”€â”€ Pick RTC module â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
MODULE="${1:-ds3231}"
case "$MODULE" in
  ds3231|ds1307|pcf8523) ;;
  *) error "Unknown module '$MODULE'. Use: ds3231 (default), ds1307, or pcf8523" ;;
esac
info "RTC module: $MODULE"

# â”€â”€ Detect boot config path (Bookworm vs older Pi OS) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if [ -f /boot/firmware/config.txt ]; then
  CONFIG=/boot/firmware/config.txt
else
  CONFIG=/boot/config.txt
fi
info "Boot config: $CONFIG"

# â”€â”€ Step 1: Enable I2C â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
info "Enabling I2C interface..."
if ! grep -q "^dtparam=i2c_arm=on" "$CONFIG"; then
  echo "dtparam=i2c_arm=on" >> "$CONFIG"
  info "I2C enabled in $CONFIG"
else
  info "I2C already enabled"
fi

# Make sure the i2c-dev module loads on boot
if ! grep -q "^i2c-dev" /etc/modules; then
  echo "i2c-dev" >> /etc/modules
fi
modprobe i2c-dev 2>/dev/null || true

# â”€â”€ Step 2: Install tools â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
info "Installing i2c-tools and python3-smbus..."
apt-get update -qq
apt-get install -y i2c-tools python3-smbus

# â”€â”€ Step 3: Add RTC device tree overlay â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
info "Adding dtoverlay for $MODULE..."
if grep -q "dtoverlay=i2c-rtc" "$CONFIG"; then
  # Replace existing RTC overlay line
  sed -i "s|dtoverlay=i2c-rtc.*|dtoverlay=i2c-rtc,$MODULE|" "$CONFIG"
  info "Updated existing dtoverlay line"
else
  echo "dtoverlay=i2c-rtc,$MODULE" >> "$CONFIG"
  info "Added dtoverlay=i2c-rtc,$MODULE to $CONFIG"
fi

# â”€â”€ Step 4: Remove fake-hwclock â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
info "Removing fake-hwclock..."
apt-get -y remove --purge fake-hwclock 2>/dev/null || true
update-rc.d -f fake-hwclock remove 2>/dev/null || true
systemctl disable fake-hwclock 2>/dev/null || true
info "fake-hwclock removed"

# â”€â”€ Step 5: Patch /lib/udev/hwclock-set â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
HWCLOCK_SET=/lib/udev/hwclock-set
if [ -f "$HWCLOCK_SET" ]; then
  info "Patching $HWCLOCK_SET to allow RTC reads under systemd..."
  # Comment out the three lines that bail out under systemd
  sed -i \
    -e 's|^if \[ -e /run/systemd/system \]|#if [ -e /run/systemd/system ]|' \
    -e 's|^ exit 0$|# exit 0|' \
    -e 's|^fi$|#fi|' \
    "$HWCLOCK_SET"
  info "Patched $HWCLOCK_SET"
else
  warn "$HWCLOCK_SET not found â€” skipping patch (may not be needed on this OS version)"
fi

# â”€â”€ Step 6: Early-boot service â€” read RTC â†’ system clock (no network needed) â”€
info "Installing rtc-restore service (reads RTC before network starts)..."
cat > /etc/systemd/system/rtc-restore.service << 'SERVICE'
[Unit]
Description=Restore system clock from hardware RTC
DefaultDependencies=no
Before=sysinit.target network-pre.target
After=dev-rtc0.device

[Service]
Type=oneshot
ExecStart=/sbin/hwclock --hctosys
RemainAfterExit=yes

[Install]
WantedBy=sysinit.target
SERVICE
systemctl daemon-reload
systemctl enable rtc-restore.service
info "rtc-restore.service enabled"

# â”€â”€ Step 7: Online-sync script â€” NTP synced â†’ write back to RTC â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
info "Installing NTPâ†’RTC sync script..."
cat > /usr/local/bin/rtc-ntp-sync.sh << 'SYNC'
#!/bin/bash
# Run after network: wait for NTP sync then write accurate time back to RTC
LOG=/var/log/hwclock-sync.log

# Check basic internet reachability
if ! ping -c1 -W10 8.8.8.8 > /dev/null 2>&1; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') [rtc-sync] No internet â€” using RTC time as-is" >> "$LOG"
  exit 0
fi

# Wait up to 60s for systemd-timesyncd to confirm NTP sync
for i in $(seq 1 12); do
  if timedatectl show --property=NTPSynchronized --value 2>/dev/null | grep -q "^yes$"; then
    /sbin/hwclock --systohc
    echo "$(date '+%Y-%m-%d %H:%M:%S') [rtc-sync] NTP synced â€” RTC updated" >> "$LOG"
    exit 0
  fi
  sleep 5
done

echo "$(date '+%Y-%m-%d %H:%M:%S') [rtc-sync] NTP did not sync in time â€” RTC unchanged" >> "$LOG"
SYNC
chmod +x /usr/local/bin/rtc-ntp-sync.sh

# Systemd service that runs the sync script after network is up
cat > /etc/systemd/system/rtc-ntp-sync.service << 'SERVICE'
[Unit]
Description=Sync NTP time back to hardware RTC when online
After=network-online.target systemd-timesyncd.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/rtc-ntp-sync.sh

[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload
systemctl enable rtc-ntp-sync.service
info "rtc-ntp-sync.service enabled"

# â”€â”€ Step 8: Nightly cron as belt-and-suspenders backup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
info "Adding nightly RTC sync cron job..."
CRON_LINE="0 2 * * * /usr/local/bin/rtc-ntp-sync.sh"
( crontab -l 2>/dev/null | grep -v "hwclock\|rtc-ntp-sync"; echo "$CRON_LINE" ) | crontab -
info "Cron job added: syncs NTP â†’ RTC at 02:00 daily"

# â”€â”€ Done â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo ""
echo -e "${GREEN}â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—${NC}"
echo -e "${GREEN}â•‘  RTC setup complete. A reboot is required.       â•‘${NC}"
echo -e "${GREEN}â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•${NC}"
echo ""
echo "After reboot, run these to verify and set the time:"
echo ""
echo "  sudo i2cdetect -y 1           # Should show 'UU' at 0x68"
echo "  sudo hwclock -r               # Read time from RTC"
echo "  sudo hwclock -w               # Write system time to RTC"
echo "  timedatectl                   # Confirm RTC = system time"
echo ""
echo "If the Pi has no internet, set time manually first:"
echo "  sudo date -s \"$(date '+%Y-%m-%d %H:%M:%S')\""
echo "  sudo hwclock -w"
echo ""

read -rp "Reboot now? [y/N]: " REBOOT
if [[ "$REBOOT" =~ ^[Yy]$ ]]; then
  info "Rebooting..."
  reboot
else
  warn "Remember to reboot before testing the RTC."
fi
