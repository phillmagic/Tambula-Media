# 📦 GITHUB REPOSITORY - FILES TO UPLOAD

## ✅ Required Files for Repository

Upload these files to: `https://github.com/phillmagic/Tambula-Media`

### **1. Main Installer** (REQUIRED)
```
setup.sh
```
**Purpose:** One-command installation script for both client and server
**Users will run:** 
```bash
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s ...
```

---

### **2. Application Files** (REQUIRED)

```
signage-client-analytics.py
```
**Purpose:** Bus client application (with analytics)

```
park-server-new.py
```
**Purpose:** Park server application

---

### **3. Documentation** (REQUIRED)

```
README.md
```
**Purpose:** Main documentation with installation instructions

```
QUICK_START.md
```
**Purpose:** Simple guide for non-technical users

```
DEPLOYMENT_CHECKLIST.md
```
**Purpose:** Fleet deployment checklist

---

### **4. Optional Files** (RECOMMENDED)

```
LICENSE
```
**Purpose:** MIT License or your choice

```
.gitignore
```
**Purpose:** Ignore .env files and logs

**Contents:**
```gitignore
# Environment variables
.env
*.env

# Logs
logs/
*.log

# Python
__pycache__/
*.py[cod]
*$py.class
venv/

# System
.DS_Store
Thumbs.db

# Media files
videos/
*.mp4
*.avi
*.mov

# Cache
cache/
*.json
```

---

### **5. Template Files** (OPTIONAL)

```
client.env.template
```
**Purpose:** Example configuration for clients

**Contents:**
```bash
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_ANON_KEY=your_anon_key_here
GROUP_ID=your_group_id_here
DEVICE_NAME=Bus-001
DEVICE_ID=auto_detected
VIDEO_DIR=/home/pi/signage/videos
CHECK_INTERVAL=60
PARK_SERVER_IP=192.168.1.100
PARK_SERVER_PORT=8080
SYNC_INTERVAL=60
```

```
server.env.template
```
**Purpose:** Example configuration for server

**Contents:**
```bash
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_ANON_KEY=your_anon_key_here
GROUP_ID=your_group_id_here
SERVER_NAME=Park-Server-Main
SERVER_PORT=8080
SYNC_INTERVAL=600
# SUPABASE_SERVICE_ROLE_KEY=your_service_key_for_analytics
```

---

## 📁 Repository Structure

```
Tambula-Media/
├── README.md                          # Main documentation
├── QUICK_START.md                     # Simple guide
├── DEPLOYMENT_CHECKLIST.md            # Fleet rollout guide
├── LICENSE                            # License file
├── .gitignore                         # Git ignore rules
├── setup.sh                           # Main installer
├── signage-client-analytics.py        # Client application
├── park-server-new.py                 # Server application
├── client.env.template                # Client config template
└── server.env.template                # Server config template
```

---

## 🚀 Installation Commands

After uploading to GitHub, users can install with:

### **Bus Client:**
```bash
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \
  "https://chjxepwsxwizvzmmawpx.supabase.co" \
  "eyJhbGc..." \
  "de437e39-5628-44fe-9657-21e65013dcf1" \
  "UBE575L" \
  "client"
```

### **Park Server:**
```bash
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \
  "https://chjxepwsxwizvzmmawpx.supabase.co" \
  "eyJhbGc..." \
  "de437e39-5628-44fe-9657-21e65013dcf1" \
  "Kampala-Park-Server" \
  "server"
```

---

## ✅ Pre-Upload Checklist

### **Before Pushing to GitHub:**

- [ ] Remove any sensitive data from files
- [ ] Remove actual API keys from examples
- [ ] Test setup.sh on fresh Pi
- [ ] Verify all URLs point to correct repo
- [ ] Check file permissions (setup.sh should be executable)
- [ ] Verify Python scripts work
- [ ] Test documentation links
- [ ] Add LICENSE file
- [ ] Add .gitignore

---

## 🔐 Security Notes

### **NEVER commit these to GitHub:**
- ❌ Actual Supabase keys
- ❌ Service role keys
- ❌ .env files with real data
- ❌ Video files
- ❌ Cache files
- ❌ Log files
- ❌ Private IP addresses

### **Safe to commit:**
- ✅ Template files (.env.template)
- ✅ Example commands (with placeholder keys)
- ✅ Documentation
- ✅ Installation scripts
- ✅ Python source code

---

## 📝 Quick Upload Steps

### **Method 1: GitHub Web Interface**

1. Go to https://github.com/phillmagic/Tambula-Media
2. Click "Add file" → "Upload files"
3. Drag and drop files
4. Commit changes

### **Method 2: Git Command Line**

```bash
# Clone repo
git clone https://github.com/phillmagic/Tambula-Media.git
cd Tambula-Media

# Copy files
cp setup.sh Tambula-Media/
cp signage-client-analytics.py Tambula-Media/
cp park-server-new.py Tambula-Media/
cp README.md Tambula-Media/
cp QUICK_START.md Tambula-Media/
cp DEPLOYMENT_CHECKLIST.md Tambula-Media/

# Add and commit
git add .
git commit -m "Initial commit - Tambula Signage System"
git push origin main
```

---

## 🧪 Testing After Upload

### **Test the installer:**

```bash
# On a fresh Raspberry Pi:
curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \
  "DUMMY_URL" \
  "DUMMY_KEY" \
  "DUMMY_ID" \
  "TEST-DEVICE" \
  "client"
```

Should show:
- Script downloads correctly
- All dependencies install
- Service created
- Configuration files generated

---

## 📊 Repository Settings

### **Recommended Settings:**

1. **Add Description:**
   "Professional digital signage system for buses with intelligent content distribution"

2. **Add Topics:**
   - digital-signage
   - raspberry-pi
   - python
   - kiosk
   - video-player
   - fleet-management

3. **Enable:**
   - Issues
   - Wiki (optional)
   - Discussions (optional)

4. **Branch Protection:**
   - Protect main branch
   - Require pull request reviews

---

## 🎉 You're Done!

After uploading, your repository will enable:

✅ **One-command installation** for anyone  
✅ **Easy fleet deployment** with documented process  
✅ **Professional documentation** for users  
✅ **Simple troubleshooting** guides  
✅ **Maintenance checklists** for operations  

**Users can install with a single command!** 🚀

---

## 📞 Next Steps

1. **Upload files to GitHub**
2. **Test installation on one Pi**
3. **Share installation command with team**
4. **Deploy to test bus**
5. **Monitor for one week**
6. **Deploy to full fleet**

**Repository URL:**  
`https://github.com/phillmagic/Tambula-Media`

**Installation URL:**  
`https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh`

---

**Happy Deploying!** 🎬
