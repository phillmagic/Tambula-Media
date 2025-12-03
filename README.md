# 🎬 Tambula Digital Signage System

**Professional digital signage system for buses and public spaces with intelligent content distribution and offline capability.**

---

## ✨ Features

### 🚌 **Bus Client**
- ✅ Auto-play video content with scheduled playlists
- ✅ Advertisement breaks with pause/resume
- ✅ Smart queue updates (no playback interruption)
- ✅ **Dual-mode sync**: Park Server (fast LAN) + Supabase (internet fallback)
- ✅ Full offline mode with local cache
- ✅ Device analytics and uptime tracking
- ✅ Auto-start on boot (kiosk mode)
- ✅ HDMI audio support
- ✅ Vertical video support

### 🏢 **Park Server**
- ✅ Content distribution hub for local network
- ✅ Auto-sync from Supabase every 10 minutes
- ✅ Serves content to multiple buses simultaneously
- ✅ Bandwidth optimization (LAN vs internet)
- ✅ Client device tracking
- ✅ Analytics and monitoring
- ✅ RESTful API

---

## 🚀 Quick Install

### **One-Command Installation**

#### **For Bus Client:**
```bash
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \
  "https://YOUR_PROJECT.supabase.co" \
  "YOUR_ANON_KEY" \
  "YOUR_GROUP_ID" \
  "DEVICE_NAME" \
  "client"
```

**Example:**
```bash
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \
  "https://chjxepwsxwizvzmmawpx.supabase.co" \
  "eyJhbGc..." \
  "de437e39-5628-44fe-9657-21e65013dcf1" \
  "UBE575L" \
  "client"
```

#### **For Park Server:**
```bash
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \
  "https://YOUR_PROJECT.supabase.co" \
  "YOUR_ANON_KEY" \
  "YOUR_GROUP_ID" \
  "SERVER_NAME" \
  "server"
```

**Example:**
```bash
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \
  "https://chjxepwsxwizvzmmawpx.supabase.co" \
  "eyJhbGc..." \
  "de437e39-5628-44fe-9657-21e65013dcf1" \
  "Kampala-Park-Server" \
  "server"
```

**During installation, you'll be prompted to enter:**
- Park Server IP address (for clients)
- Park Server port (default: 8080)

---

## 📋 Requirements

### **Hardware:**
- Raspberry Pi 4 (2GB+ RAM recommended)
- 32GB+ microSD card
- HDMI display
- Network connection (WiFi or Ethernet)

### **Software:**
- Raspberry Pi OS (Desktop or Lite)
- Internet connection for initial setup
- Supabase account

---

## 🏗️ System Architecture

```
┌────────────────────────────────────────┐
│       SUPABASE (Cloud)                 │
│   - Video Storage                      │
│   - Schedules & Playlists             │
│   - Settings & Analytics              │
└───────────────┬────────────────────────┘
                │
                │ Sync (10 min)
                ▼
┌────────────────────────────────────────┐
│     PARK SERVER (Raspberry Pi)         │
│   IP: 192.168.1.100                    │
│   - Local content cache                │
│   - Fast LAN distribution              │
│   - Device tracking                    │
└───────────────┬────────────────────────┘
                │
                │ Park WiFi (1 min)
       ┌────────┼────────┐
       │        │        │
┌──────▼─┐ ┌───▼───┐ ┌──▼──────┐
│ BUS #1 │ │BUS #2 │ │ BUS #3  │
│ Client │ │Client │ │ Client  │
│ Plays  │ │       │ │         │
│ Videos │ │       │ │         │
└────────┘ └───────┘ └─────────┘
```

### **Data Flow:**
1. **Upload content** → Supabase Storage
2. **Park Server syncs** → Downloads from Supabase (every 10 min)
3. **Bus connects** → Downloads from Park Server (fast LAN)
4. **Away from park** → Falls back to Supabase
5. **Offline** → Uses cached content

---

## 📖 Installation Guide

### **Step 1: Get Your Credentials**

From Supabase Dashboard:
1. Go to **Settings → API**
2. Copy **Project URL** (e.g., `https://xxx.supabase.co`)
3. Copy **anon/public** key
4. Note your **GROUP_ID** (from your database)

### **Step 2: Prepare Raspberry Pi**

```bash
# Flash Raspberry Pi OS
# Boot and connect to network
# SSH into the Pi
ssh pi@raspberrypi.local
```

### **Step 3: Run Installer**

**For Bus Client:**
```bash
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \
  "SUPABASE_URL" \
  "ANON_KEY" \
  "GROUP_ID" \
  "DEVICE_NAME" \
  "client"
```

**For Park Server:**
```bash
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \
  "SUPABASE_URL" \
  "ANON_KEY" \
  "GROUP_ID" \
  "SERVER_NAME" \
  "server"
```

### **Step 4: Configure Park Server IP** (for clients only)

During installation, when prompted:
```
Enter Park Server IP address: 192.168.1.100
Park Server Port [8080]: 8080
```

Or skip to use Supabase-only mode (no local server).

### **Step 5: Reboot & Test**

```bash
sudo reboot
```

**Client:** Should boot directly to fullscreen video player
**Server:** Check status at `http://SERVER_IP:8080/status`

---

## 🛠️ Configuration

### **Client Configuration** (`~/signage/.env`)

```bash
# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=your_key
GROUP_ID=your_group_id

# Device
DEVICE_NAME=Bus 001
DEVICE_ID=auto_detected

# Park Server (Optional)
PARK_SERVER_IP=192.168.1.100
PARK_SERVER_PORT=8080
SYNC_INTERVAL=60
```

### **Server Configuration** (`~/park-server/.env`)

```bash
# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=your_key
GROUP_ID=your_group_id

# Server
SERVER_NAME=Park-Server-Kampala
SERVER_PORT=8080
SYNC_INTERVAL=600

# Optional: For analytics
# SUPABASE_SERVICE_ROLE_KEY=your_service_key
```

---

## 📊 Usage

### **Check Status**

```bash
# Client
sudo systemctl status tambula-signage
tail -f ~/signage/logs/signage.log

# Server
sudo systemctl status tambula-park-server
tail -f ~/park-server/logs/park-server.log
```

### **Restart Service**

```bash
# Client
sudo systemctl restart tambula-signage

# Server
sudo systemctl restart tambula-park-server
```

### **View Logs**

```bash
# Client
tail -f ~/signage/logs/signage.log
tail -f ~/signage/logs/kiosk.log

# Server
tail -f ~/park-server/logs/park-server.log
```

### **API Endpoints**

**Client:**
- `http://localhost:8080/` - Video player
- `http://localhost:8080/status` - Status info

**Server:**
- `http://SERVER_IP:8080/` - Server info
- `http://SERVER_IP:8080/status` - Server status
- `http://SERVER_IP:8080/api/videos` - List videos
- `http://SERVER_IP:8080/api/manifest` - File manifest

---

## 🔧 Troubleshooting

### **Client won't start:**
```bash
# Check service status
sudo systemctl status tambula-signage

# Check logs
tail -50 ~/signage/logs/signage.log

# Restart
sudo systemctl restart tambula-signage
```

### **No video playback:**
```bash
# Check if server is running
curl http://localhost:8080/status

# Check if videos downloaded
ls -lh ~/signage/videos/

# Check cache
cat ~/signage/cache/manifest.json
```

### **Can't connect to park server:**
```bash
# Test connection
ping 192.168.1.100
curl http://192.168.1.100:8080/status

# Check .env configuration
cat ~/signage/.env | grep PARK_SERVER
```

### **No audio:**
```bash
# Test audio
speaker-test -t wav -c 2 -l 1

# Check HDMI audio
amixer cget numid=3

# Force HDMI
amixer cset numid=3 2
```

---

## 🎮 Keyboard Controls (Client)

When in kiosk mode:
- **F** or **F11** - Toggle fullscreen
- **N** - Next video
- **P** - Previous video
- **A** - Manual advert trigger (testing)
- **ESC** - Exit fullscreen

---

## 📱 Features in Detail

### **Smart Sync System**

**Priority:**
1. **Park Server** (LAN) - Fast, local
2. **Supabase** (Internet) - Reliable fallback
3. **Cache** (Offline) - Autonomous operation

**Sync Frequency:**
- Park Server → Supabase: Every 10 minutes
- Bus Client → Park Server: Every 1 minute
- Metadata refresh: Every 30 seconds

### **Offline Mode**

Clients work fully offline:
- ✅ Plays cached videos
- ✅ Follows cached schedules
- ✅ Shows cached playlists
- ✅ Displays cached logo
- ✅ Advert breaks continue

Background sync keeps trying to reconnect.

### **Analytics**

Tracks (when online):
- Device uptime
- Videos played
- Adverts shown
- Playback statistics
- Connection status
- Error logs

### **Kiosk Mode**

Auto-start features:
- ✅ Boots directly to video player
- ✅ Fullscreen (no desktop)
- ✅ Hidden cursor
- ✅ No screen blanking
- ✅ Auto-restart on crash
- ✅ No keyring prompts

---

## 🔐 Security Notes

### **API Keys:**
- **Anon Key** - Safe for clients (read-only)
- **Service Role Key** - Server only (never expose)

### **Network:**
- Park Server should be on secure network
- Use firewall rules if needed
- SSH key authentication recommended

### **Data:**
- Videos cached locally
- Database credentials in `.env`
- Keep `.env` file secure

---

## 📦 What Gets Installed

### **Client:**
```
~/signage/
├── signage-client.py     # Main application
├── .env                  # Configuration
├── start-signage-kiosk.sh # Kiosk launcher
├── videos/               # Cached videos
├── assets/               # Logos, images
├── cache/                # Metadata cache
└── logs/                 # Application logs

/etc/systemd/system/
└── tambula-signage.service

~/.config/autostart/
└── tambula-signage.desktop
```

### **Server:**
```
~/park-server/
├── park-server.py        # Main application
├── .env                  # Configuration
├── videos/               # Cached videos
├── assets/               # Logos, images
├── cache/                # Metadata cache
└── logs/                 # Application logs

/etc/systemd/system/
└── tambula-park-server.service
```

---

## 🚀 Deployment Tips

### **For Bus Fleet:**

1. **Set up one test bus first**
   - Monitor for 1 week
   - Verify all features work
   - Document any issues

2. **Deploy park server**
   - Install at central location
   - Configure static IP
   - Test with one client

3. **Roll out to fleet**
   - 2-3 buses per day
   - Monitor each deployment
   - Keep checklist

### **For Multiple Parks:**

Each park gets its own server:
- Park 1: `192.168.1.100`
- Park 2: `192.168.2.100`
- Park 3: `192.168.3.100`

Clients auto-detect correct server based on network.

---

## 🔄 Updates

### **Update Client:**
```bash
cd ~/signage
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/signage-client-analytics.py -o signage-client.py
sudo systemctl restart tambula-signage
```

### **Update Server:**
```bash
cd ~/park-server
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/park-server-new.py -o park-server.py
sudo systemctl restart tambula-park-server
```

---

## 📞 Support

**Issues?** Open an issue on GitHub with:
- Device type (client/server)
- Raspberry Pi model
- OS version (`uname -a`)
- Logs (`~/signage/logs/`)
- Steps to reproduce

---

## 📄 License

MIT License - See LICENSE file

---

## 🙏 Credits

Built for Tambula Transport Solutions
Developed by [Your Name/Team]

---

**Happy Signage! 🎬**
