#!/usr/bin/env python3
"""
ESP32 Multi-Device OTA Trigger Script

Trigger OTA updates for multiple devices simultaneously.

Usage:
    python trigger_ota_multi.py <firmware_path_or_url> <device_id1> <device_id2> <device_id3> ...
    
Examples:
    # Update 3 devices
    python trigger_ota_multi.py firmware.bin 7 8 9
    
    # Update from GitHub URL
    python trigger_ota_multi.py https://raw.githubusercontent.com/user/repo/main/firmware.bin 7 8 9
    
    # Update many devices
    python trigger_ota_multi.py firmware.bin 1 2 3 4 5 6 7 8 9 10
"""

import sys
import json
import os
import tempfile
import time

def trigger_ota_multi(firmware_source, device_ids):
    """Create OTA trigger files for multiple devices"""
    
    print("🚀 Multi-Device OTA Trigger")
    print("=" * 60)
    print(f"📦 Firmware: {firmware_source}")
    print(f"🎯 Target devices: {', '.join(map(str, device_ids))}")
    print(f"📊 Total devices: {len(device_ids)}")
    print()
    
    temp_dir = tempfile.gettempdir()
    success_count = 0
    
    for device_id in device_ids:
        command = {
            "device_id": device_id,
            "firmware": firmware_source
        }
        
        # Create unique filename for each device
        ota_file = os.path.join(temp_dir, f"esp_ota_command_{device_id}.json")
        
        try:
            with open(ota_file, 'w') as f:
                json.dump(command, f, indent=2)
            
            print(f"✅ Device {device_id}: Trigger created")
            success_count += 1
            
            # Small delay between triggers to avoid overwhelming the system
            time.sleep(0.1)
            
        except Exception as e:
            print(f"❌ Device {device_id}: Error - {e}")
    
    print()
    print("=" * 60)
    print(f"📊 Summary: {success_count}/{len(device_ids)} triggers created")
    print()
    print("⏳ The listener will process these automatically")
    print("   Updates will run in parallel for all devices")
    print()
    print("💡 Expected timeline:")
    print(f"   • Detection: ~2 seconds per device")
    print(f"   • Download: Once (shared for all)")
    print(f"   • Transfers: Parallel (~3-5 minutes each)")
    print(f"   • Total time: ~5-7 minutes for all devices")
    print()

def main():
    if len(sys.argv) < 3:
        print("Usage: python trigger_ota_multi.py <firmware> <device_id1> [device_id2] ...")
        print("\nExamples:")
        print("  python trigger_ota_multi.py firmware.bin 7 8 9")
        print("  python trigger_ota_multi.py https://github.com/.../firmware.bin 1 2 3 4 5")
        sys.exit(1)
    
    firmware_source = sys.argv[1]
    
    # Parse device IDs
    try:
        device_ids = [int(arg) for arg in sys.argv[2:]]
        
        # Validate device IDs
        invalid_ids = [did for did in device_ids if did < 1 or did > 255]
        if invalid_ids:
            print(f"❌ Invalid Device IDs (must be 1-255): {invalid_ids}")
            sys.exit(1)
        
        # Check for duplicates
        if len(device_ids) != len(set(device_ids)):
            print("❌ Duplicate Device IDs detected")
            sys.exit(1)
        
        trigger_ota_multi(firmware_source, device_ids)
        
    except ValueError:
        print("❌ All device IDs must be numbers")
        sys.exit(1)

if __name__ == "__main__":
    main()
