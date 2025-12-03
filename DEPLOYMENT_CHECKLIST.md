# 📋 Tambula Signage - Fleet Deployment Checklist

## 🎯 Pre-Deployment Preparation

### **Gather Information**
- [ ] Supabase Project URL: ______________________
- [ ] Supabase Anon Key: ______________________
- [ ] Group ID: ______________________
- [ ] Park Server IP (if using): ______________________
- [ ] Number of buses: ______
- [ ] Number of park servers: ______

### **Hardware Inventory**
- [ ] Raspberry Pi 4 units: ______ (need: ______)
- [ ] microSD cards (32GB+): ______ (need: ______)
- [ ] Power supplies: ______ (need: ______)
- [ ] HDMI cables: ______ (need: ______)
- [ ] Displays/TVs: ______ (need: ______)
- [ ] Keyboards (for setup): ______ (need: ______)
- [ ] Spare SD cards for backup: ______

### **Test Environment**
- [ ] Test Pi set up (bench testing)
- [ ] Internet connectivity verified
- [ ] Supabase connection tested
- [ ] Video playback tested
- [ ] Audio output tested
- [ ] Kiosk mode tested
- [ ] Auto-start on boot tested
- [ ] Offline mode tested

---

## 🏗️ Phase 1: Park Server Setup

**Location:** ______________________  
**Installation Date:** ______________________  
**Technician:** ______________________

### **Pre-Installation**
- [ ] Static IP assigned: ______________________
- [ ] Network access confirmed
- [ ] Power outlet available
- [ ] Mounting location determined

### **Installation**
- [ ] Flash SD card with Raspberry Pi OS
- [ ] Boot and configure network
- [ ] SSH access confirmed
- [ ] Run installation command:
  ```bash
  curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \
    "SUPABASE_URL" \
    "ANON_KEY" \
    "GROUP_ID" \
    "SERVER_NAME" \
    "server"
  ```
- [ ] Installation completed successfully
- [ ] Service status: ☐ Running ☐ Failed
- [ ] API accessible: `curl http://SERVER_IP:8080/status`

### **Post-Installation**
- [ ] Verify sync from Supabase working
- [ ] Videos downloading to ~/park-server/videos/
- [ ] Manifest generated: ~/park-server/cache/manifest.json
- [ ] Server registered in network
- [ ] Logs checked for errors
- [ ] Server IP documented: ______________________

### **24-Hour Check**
**Date/Time:** ______________________
- [ ] Server still running
- [ ] No error logs
- [ ] Videos updated from Supabase
- [ ] Disk space OK: ______ GB free

---

## 🚌 Phase 2: Bus Client Deployment

### **Bus Information Template**

Use this for each bus:

---

**Bus ID:** ________ (e.g., Bus-001)  
**Registration/Plate:** ______________________  
**Installation Date:** ______________________  
**Technician:** ______________________

#### **Hardware Details**
- [ ] Pi Serial Number: ______________________
- [ ] SD Card ID: ______________________
- [ ] Display Model: ______________________
- [ ] Mounted Location: ______________________

#### **Pre-Installation**
- [ ] SD card flashed with Raspberry Pi OS
- [ ] WiFi credentials configured
- [ ] SSH enabled
- [ ] Display connected and tested
- [ ] Power supply connected

#### **Installation**
- [ ] Boot Pi and verify network connection
- [ ] SSH access confirmed: `ssh pi@HOSTNAME`
- [ ] Run installation command:
  ```bash
  curl -sSL https://raw.githubusercontent.com/phillmagic/Tambula-Media/main/setup.sh | sudo bash -s \
    "SUPABASE_URL" \
    "ANON_KEY" \
    "GROUP_ID" \
    "BUS_ID" \
    "client"
  ```
- [ ] Entered Park Server IP: ______________________
- [ ] Installation completed: ☐ Success ☐ Failed
- [ ] System rebooted
- [ ] Kiosk mode started automatically

#### **Testing**
- [ ] Display shows fullscreen video
- [ ] Audio output working (HDMI)
- [ ] Logo displays in top-right
- [ ] Status overlay visible
- [ ] No error messages
- [ ] Auto-start on boot works
- [ ] Can exit fullscreen (F11/ESC)
- [ ] Playlist updates work
- [ ] Advertisement breaks work

#### **Network Configuration**
- [ ] IP Address: ______________________
- [ ] Hostname: ______________________
- [ ] Connected to: ☐ Park WiFi ☐ 4G/LTE ☐ Other
- [ ] Can reach park server: ☐ Yes ☐ No ☐ N/A
- [ ] Can reach Supabase: ☐ Yes ☐ No

#### **Offline Test** (Optional but recommended)
- [ ] Disconnect from network
- [ ] Videos continue playing from cache
- [ ] No errors displayed
- [ ] Reconnect network
- [ ] Sync resumes automatically

#### **Final Checks**
- [ ] Cable management completed
- [ ] Power supply secured
- [ ] Display mounted properly
- [ ] Pi mounted/secured
- [ ] No exposed wires
- [ ] Driver instructed on operation
- [ ] Emergency contact provided

#### **Documentation**
- [ ] IP address recorded
- [ ] Device ID recorded: ______________________
- [ ] Photo taken of installation
- [ ] Installation log saved
- [ ] Checklist filed

#### **Sign-Off**
- Technician: ______________________ Date: ______
- Supervisor: ______________________ Date: ______
- Driver Acceptance: ______________________ Date: ______

---

## 📊 Fleet Deployment Summary

### **Deployment Schedule**

| Date | Bus ID | Status | Technician | Notes |
|------|--------|--------|------------|-------|
| _____ | Bus-001 | ☐ ✓ ☐ ✗ | _________ | _____ |
| _____ | Bus-002 | ☐ ✓ ☐ ✗ | _________ | _____ |
| _____ | Bus-003 | ☐ ✓ ☐ ✗ | _________ | _____ |
| _____ | Bus-004 | ☐ ✓ ☐ ✗ | _________ | _____ |
| _____ | Bus-005 | ☐ ✓ ☐ ✗ | _________ | _____ |
| _____ | Bus-006 | ☐ ✓ ☐ ✗ | _________ | _____ |
| _____ | Bus-007 | ☐ ✓ ☐ ✗ | _________ | _____ |
| _____ | Bus-008 | ☐ ✓ ☐ ✗ | _________ | _____ |
| _____ | Bus-009 | ☐ ✓ ☐ ✗ | _________ | _____ |
| _____ | Bus-010 | ☐ ✓ ☐ ✗ | _________ | _____ |

**Legend:** ✓ = Completed, ✗ = Failed/Issue

### **Deployment Statistics**

- Total Buses: ______
- Deployed: ______
- Pending: ______
- Failed: ______
- Success Rate: ______%
- Average Install Time: ______ minutes

---

## 🔍 Phase 3: Post-Deployment Monitoring

### **Day 1 Checks** (After Installation)

**For Each Bus:**
- [ ] Service running: `systemctl status tambula-signage`
- [ ] No errors in logs: `tail -50 ~/signage/logs/signage.log`
- [ ] Videos playing correctly
- [ ] Display working properly
- [ ] Driver feedback collected

### **Week 1 Checks** (Daily)

**Date: ______** Time: ______

| Bus ID | Online | Playing | Errors | Notes |
|--------|--------|---------|--------|-------|
| Bus-001 | ☐ | ☐ | ☐ | _____ |
| Bus-002 | ☐ | ☐ | ☐ | _____ |
| Bus-003 | ☐ | ☐ | ☐ | _____ |
| Bus-004 | ☐ | ☐ | ☐ | _____ |
| Bus-005 | ☐ | ☐ | ☐ | _____ |

Repeat for remaining buses...

### **Common Issues Log**

| Date | Bus ID | Issue | Resolution | Time |
|------|--------|-------|------------|------|
| _____ | ______ | _____ | __________ | ____ |
| _____ | ______ | _____ | __________ | ____ |
| _____ | ______ | _____ | __________ | ____ |

---

## 🛠️ Maintenance Schedule

### **Daily** (Automated)
- [ ] Sync checks (automated)
- [ ] Log rotation (automated)
- [ ] Health monitoring (automated)

### **Weekly**
- [ ] Review system logs
- [ ] Check disk space on all devices
- [ ] Verify all buses still online
- [ ] Address any reported issues

### **Monthly**
- [ ] System updates review
- [ ] Performance analysis
- [ ] Content refresh verification
- [ ] Hardware inspection

### **Quarterly**
- [ ] Full system audit
- [ ] SD card health check
- [ ] Replace aging hardware
- [ ] Driver training refresh

---

## 📞 Support Contacts

**Primary Support:**
- Name: ______________________
- Phone: ______________________
- Email: ______________________

**Technical Support:**
- Name: ______________________
- Phone: ______________________
- Email: ______________________

**Vendor Support:**
- Company: ______________________
- Phone: ______________________
- Email: ______________________

**Emergency Contact:**
- Name: ______________________
- Phone: ______________________
- Available: ______________________

---

## 🎯 Success Criteria

**Deployment is successful when:**
- [ ] All buses have signage installed
- [ ] 95%+ uptime across fleet
- [ ] No critical errors in logs
- [ ] Drivers comfortable with system
- [ ] Content updates work reliably
- [ ] Offline mode works when needed
- [ ] Park server stable and reliable
- [ ] Analytics data flowing correctly

---

## 📁 Documentation

**Required Documentation:**
- [ ] Installation photos (all buses)
- [ ] Network diagram
- [ ] IP address spreadsheet
- [ ] Device ID registry
- [ ] Backup SD card images
- [ ] Configuration files backed up
- [ ] Troubleshooting guide created
- [ ] Driver instruction manual
- [ ] Maintenance procedures documented

---

## ✅ Final Sign-Off

**Project Manager:** ______________________  
**Signature:** ______________________ Date: ______

**Technical Lead:** ______________________  
**Signature:** ______________________ Date: ______

**Fleet Manager:** ______________________  
**Signature:** ______________________ Date: ______

---

**Deployment Complete!** 🎉

**Next Steps:**
1. Monitor system for 30 days
2. Collect driver feedback
3. Address any issues
4. Optimize based on usage
5. Plan for future enhancements

---

**Document Version:** 1.0  
**Last Updated:** ______________________  
**Next Review:** ______________________
