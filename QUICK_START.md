# 🚀 Tambula Signage - Quick Start Guide
**For Non-Technical Users**

---

## 📱 What You Need

1. **Raspberry Pi 4** (small computer)
2. **TV/Display** with HDMI
3. **WiFi** or **Ethernet** connection
4. **Power supply** for Raspberry Pi
5. **These details** from your Supabase account:
   - Project URL
   - API Key
   - Group ID

---

## 🎯 Installation in 3 Steps

### **STEP 1: Prepare Raspberry Pi**

1. **Flash SD card** with Raspberry Pi OS
   - Download Raspberry Pi Imager
   - Choose "Raspberry Pi OS (32-bit)"
   - Configure WiFi and enable SSH
   - Flash to SD card

2. **Boot Raspberry Pi**
   - Insert SD card
   - Connect HDMI to TV
   - Connect power
   - Wait 2 minutes for boot

### **STEP 2: Connect via SSH**

From your computer:

**On Windows:**
- Download PuTTY
- Connect to `raspberrypi.local`
- Username: `pi`
- Password: (what you set)

**On Mac/Linux:**
```bash
ssh pi@raspberrypi.local
```

### **STEP 3: Run Installation Command**

**For a BUS (plays videos):**

Copy this command, replace the CAPITAL parts, and paste into terminal:

```bash
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s "YOUR_SUPABASE_URL" "YOUR_API_KEY" "YOUR_GROUP_ID" "BUS_NAME" "client"
```

**Real Example:**
```bash
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s "https://xxx.supabase.co" "eyJhbGc..." "de437e39..." "Bus-001" "client"
```

**For a PARK SERVER (distributes content):**

```bash
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s "YOUR_SUPABASE_URL" "YOUR_API_KEY" "YOUR_GROUP_ID" "SERVER_NAME" "server"
```

**Press Enter** and wait 5-10 minutes.

### **During Installation:**

**For Bus:**
You'll be asked:
```
Enter Park Server IP address:
```
- If you have a park server, enter its IP (e.g., `192.168.1.100`)
- If you don't have one yet, just press Enter

```
Park Server Port [8080]:
```
- Just press Enter (use default)

### **After Installation:**

**For Bus:**
```bash
sudo reboot
```

After reboot, the TV should automatically show videos in fullscreen!

**For Park Server:**

No reboot needed. Server starts automatically.

Check it's working:
```bash
curl http://localhost:8080/status
```

---

## ✅ How to Check if It's Working

### **Bus Client:**

**Good Signs:**
- ✅ Screen shows videos automatically
- ✅ No desktop visible
- ✅ Videos play smoothly
- ✅ Logo appears in corner

**Check Status:**
```bash
ssh pi@bus-ip-address
sudo systemctl status tambula-signage
```

### **Park Server:**

**Good Signs:**
- ✅ Service is running
- ✅ Can access status page
- ✅ Videos are downloading

**Check Status:**
```bash
ssh pi@server-ip-address
sudo systemctl status tambula-park-server
curl http://localhost:8080/status
```

---

## 🔧 Common Problems

### **Problem: Screen is blank**

**Fix:**
```bash
ssh pi@raspberrypi.local
sudo systemctl restart tambula-signage
sudo reboot
```

### **Problem: No videos playing**

**Check:**
```bash
# Are videos downloaded?
ls ~/signage/videos/

# Check logs
tail -f ~/signage/logs/signage.log
```

### **Problem: Can't connect to park server**

**Check:**
1. Is park server running?
   ```bash
   ping PARK_SERVER_IP
   ```

2. Is IP correct in config?
   ```bash
   cat ~/signage/.env | grep PARK_SERVER
   ```

3. Are they on same WiFi network?

### **Problem: No audio**

**Fix:**
```bash
# Test audio
speaker-test -t wav -c 2 -l 1

# If no sound, force HDMI audio
amixer cset numid=3 2

# Reboot
sudo reboot
```

---

## 📝 Useful Commands

### **Restart Everything**
```bash
sudo reboot
```

### **Stop Video Player**
```bash
sudo systemctl stop tambula-signage
```

### **Start Video Player**
```bash
sudo systemctl start tambula-signage
```

### **Check What's Wrong**
```bash
# Check service
sudo systemctl status tambula-signage

# See logs (last 50 lines)
tail -50 ~/signage/logs/signage.log

# See live logs
tail -f ~/signage/logs/signage.log
```

### **Exit Fullscreen** (if using keyboard)
- Press **F11** or **ESC**

---

## 🎮 Keyboard Shortcuts (When Testing)

If you have a keyboard connected:
- **F** or **F11** - Fullscreen on/off
- **N** - Next video
- **P** - Previous video
- **ESC** - Exit fullscreen

---

## 📊 Multiple Installations

### **Installing 10 Buses:**

For each bus, repeat:
1. Flash SD card with Raspberry Pi OS
2. Boot Pi
3. SSH in
4. Run install command with unique name:
   ```bash
   curl -sSL ... "Bus-001" "client"
   curl -sSL ... "Bus-002" "client"
   curl -sSL ... "Bus-003" "client"
   ```
5. Reboot

**Tip:** Keep a checklist!

---

## 📋 Installation Checklist

**Before Starting:**
- [ ] Raspberry Pi 4 ready
- [ ] SD card (32GB+)
- [ ] TV/Display with HDMI
- [ ] WiFi credentials
- [ ] Supabase details ready
- [ ] Device name decided

**Installation:**
- [ ] SD card flashed
- [ ] Pi booted successfully
- [ ] Connected via SSH
- [ ] Run installation command
- [ ] Entered park server IP (if applicable)
- [ ] Installation completed (no errors)
- [ ] Rebooted

**Testing:**
- [ ] Screen shows videos
- [ ] Audio works
- [ ] Logo displays
- [ ] No error messages
- [ ] Keyboard controls work
- [ ] Auto-starts on boot

---

## 🎯 What Each Device Does

### **Bus Client (Player):**
- Downloads videos
- Plays them automatically
- Shows advertisements
- Works offline
- Reports statistics

### **Park Server (Hub):**
- Downloads videos from internet
- Shares them with buses on same WiFi
- Faster than each bus downloading separately
- Tracks which buses are connected

---

## 💡 Tips for Success

1. **Test with One Bus First**
   - Install on one bus
   - Drive it for a week
   - Make sure everything works
   - Then install on others

2. **Label Everything**
   - Write IP address on each Pi
   - Label SD cards
   - Keep list of bus names

3. **Keep Backups**
   - Clone working SD card
   - Save .env files
   - Document any changes

4. **Monitor First Week**
   - Check logs daily
   - Look for errors
   - Ask for help if stuck

---

## 📞 Getting Help

**If something goes wrong:**

1. **Check the logs**
   ```bash
   tail -100 ~/signage/logs/signage.log
   ```

2. **Copy the error message**

3. **Take a photo of the screen**

4. **Contact support with:**
   - What you were trying to do
   - What happened instead
   - Error messages
   - Photos/screenshots

---

## ✅ Success!

When working properly:
- ✅ Bus boots directly to fullscreen videos
- ✅ Videos play smoothly with audio
- ✅ Logo shows in corner
- ✅ Updates happen automatically
- ✅ Works even without internet (offline mode)
- ✅ No manual intervention needed

**That's it! Your digital signage is ready!** 🎉

---

**Questions?** Open an issue on GitHub or contact your administrator.
