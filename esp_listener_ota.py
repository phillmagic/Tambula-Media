# esp_listener_ota.py
import asyncio
import serial
import serial.tools.list_ports
import aiohttp
import json
import sys
import logging
import time
import os
import subprocess
from typing import Dict, Set, Optional
from dataclasses import dataclass
from enum import Enum

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Configuration
BAUD_RATE = 2000000
API_URL = "https://edu.tambulamedia.com/api/questionnaires/answer"
MOTHER_URL = "https://edu.tambulamedia.com/api/questionnaires/mother"
MOTHER_ID = 1
TARGET_PORT = "56"

# ESP32 CP2102 IDs
ESP32_VID = 0x303A
ESP32_PID = 0x1001

# OTA Configuration
OTA_CHUNK_SIZE = 250  # Max ESP-NOW payload size
OTA_CHUNK_DELAY = 0.03  # 30ms between chunks (33 chunks/sec) - faster!
OTA_TIMEOUT = 420  # 7 minutes total timeout (for large firmware ~900KB)

class OTAStatus(Enum):
    IDLE = "idle"
    DOWNLOADING = "downloading"
    STARTING = "starting"
    SENDING = "sending"
    FINALIZING = "finalizing"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"

@dataclass
class OTASession:
    device_id: int
    firmware_path: str
    firmware_size: int
    status: OTAStatus
    bytes_sent: int
    start_time: float
    last_update: float
    error_message: Optional[str] = None

class FinalESP32Manager:
    """
    Enhanced listener with OTA update support
    """
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.active_devices: Dict[str, asyncio.Task] = {}
        self.serial_ports: Dict[str, serial.Serial] = {}
        self.session: aiohttp.ClientSession = None
        self.running = True
        
        # OTA tracking
        self.ota_sessions: Dict[int, OTASession] = {}
        self.ota_lock = asyncio.Lock()
        
        # Simple stats
        self.stats = {
            'answers_processed': 0,
            'errors': 0,
            'ota_updates': 0,
            'ota_successes': 0,
            'ota_failures': 0,
            'start_time': time.time()
        }
    
    async def __aenter__(self):
        # Simple HTTP session
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            headers={"Content-Type": "application/json"}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.shutdown()
    
    def find_esp32_ports(self) -> Set[str]:
        """Find all connected ESP32 devices"""
        ports = serial.tools.list_ports.comports()
        esp32_ports = set()
        for port in ports:
            if port.vid == ESP32_VID and port.pid == ESP32_PID and TARGET_PORT in port.device:
                esp32_ports.add(port.device)
        return esp32_ports
    
    async def get_user_input_with_timeout(self, timeout_seconds: int):
        """Get user input with a timeout (non-blocking)."""
        try:
            # Run input() in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            
            # Create a task for getting input
            input_task = loop.run_in_executor(None, input)
            
            # Wait for input with timeout
            result = await asyncio.wait_for(input_task, timeout=timeout_seconds)
            return result
        except asyncio.TimeoutError:
            print("\n⏱️  Timeout - no response provided")
            return None
        except Exception as e:
            logger.error(f"Error getting user input: {e}")
            return None

    # ==================== OTA FUNCTIONS ====================
    
    async def initiate_wifi_ota(self, device_id: int, firmware_url: str, port: str):
        """Just send URL to child - child does everything"""
        
        # Get serial port
        ser = self.serial_ports.get(port)
        if not ser:
            logger.error(f"❌ Serial port {port} not found")
            return False
        
        logger.info(f"🚀 Initiating WiFi OTA for Device {device_id}")
        logger.info(f"📡 Firmware URL: {firmware_url}")
        
        # Send WiFi OTA command
        ota_cmd = {
            "OTA_CMD": "WIFI_UPDATE",
            "Did": device_id,
            "URL": firmware_url
        }
        
        # Send via serial (async)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: ser.write((json.dumps(ota_cmd) + "\n").encode("utf-8"))
        )
        
        logger.info(f"📤 Sent WiFi OTA command to Device {device_id}")
        logger.info(f"⏳ Child will: Connect WiFi → Download → Flash → Reboot")
        logger.info(f"💡 Expected time: 30-60 seconds")
        
        self.stats['ota_updates'] += 1
        return True
    
    def handle_wifi_ota_status(self, payload: dict):
        """Handle OTA status from child"""
        device_id = payload.get("Did")
        ota_status = payload.get("OTA")
        message = payload.get("Msg", "")
        
        if ota_status == "OTA_STARTING":
            logger.info(f"📡 Device {device_id} - Connecting to WiFi...")
        
        elif ota_status == "OTA_DOWNLOADING":
            logger.info(f"📥 Device {device_id} - Downloading firmware...")
        
        elif ota_status == "OTA_FLASHING":
            logger.info(f"⚡ Device {device_id} - Flashing firmware...")
        
        elif ota_status == "OTA_SUCCESS":
            logger.info(f"🎉 Device {device_id} - Update successful!")
            self.stats['ota_successes'] += 1
        
        elif ota_status == "OTA_ERROR":
            logger.error(f"❌ Device {device_id} - OTA failed: {message}")
            self.stats['ota_failures'] += 1
            
    
    # ==================== DEVICE HANDLER ====================

    async def handle_device(self, port: str):
        """Handle a single ESP32 device - reliable and simple"""
        logger.info(f"🔌 Starting handler for {port}")
        
        try:
            # Open serial connection
            loop = asyncio.get_event_loop()
            ser = await loop.run_in_executor(
                None, 
                lambda: serial.Serial(port, BAUD_RATE, timeout=1)
            )
            self.serial_ports[port] = ser
            
            logger.info(f"✅ Connected to {port}")
            
            # Pairing state tracking
            in_pairing_mode = False
            pairing_device_id = None
            pairing_mac = None
            pairing_cooldown_until = 0
            
            while self.running:
                try:
                    # Read line-by-line (reliable approach)
                    line = await loop.run_in_executor(
                        None, lambda: ser.readline().decode("utf-8", errors="ignore").strip()
                    )
                    
                    if not line:
                        await asyncio.sleep(0.01)
                        continue

                    # ==================== PAIRING MODE DETECTION ====================
                    
                    # Check if we're in cooldown period (ignore pairing triggers for 5 seconds after responding)
                    if in_pairing_mode:
                        current_time = time.time()
                        if current_time < pairing_cooldown_until:
                            # Skip processing pairing-related lines during cooldown
                            if any(keyword in line for keyword in ["PAIRING REQUEST", "Device ID:", "MAC Address:", 
                                                                    "Do you want to become the mother", "Type 'Y'"]):
                                continue
                    
                    # Check for pairing request prompt
                    if "PAIRING REQUEST RECEIVED" in line or "🔔 PAIRING REQUEST RECEIVED" in line:
                        in_pairing_mode = True
                        pairing_device_id = None
                        pairing_mac = None
                        print(f"\n{'='*60}")
                        print(f"[{port}] 🔔 PAIRING REQUEST DETECTED!")
                        print(f"{'='*60}")
                        continue
                    
                    # Extract device ID from pairing prompt
                    if in_pairing_mode and "Device ID:" in line:
                        try:
                            pairing_device_id = line.split("Device ID:")[1].strip()
                            print(f"[{port}] 📱 Device ID: {pairing_device_id}")
                        except:
                            pass
                        continue
                    
                    # Extract MAC address from pairing prompt
                    if in_pairing_mode and "MAC Address:" in line:
                        try:
                            pairing_mac = line.split("MAC Address:")[1].strip()
                            print(f"[{port}] 📡 MAC Address: {pairing_mac}")
                        except:
                            pass
                        continue
                    
                    # Show the actual prompt question
                    if in_pairing_mode and "Do you want to become the mother" in line:
                        print(f"[{port}] 🤔 Do you want to become the mother for this device?")
                        continue
                    
                    if in_pairing_mode and ("Type 'Y'" in line or "Type 'y'" in line):
                        print(f"[{port}] 💡 Type 'Y' to accept, 'N' to reject, or wait 30s to timeout")
                        
                        # Prompt user for input in a non-blocking way
                        print(f"\n>>> PAIRING REQUEST from Device {pairing_device_id} <<<")
                        print(f">>> Do you want to pair? (Y/N): ", end='', flush=True)
                        
                        # Wait for user input with timeout (30 seconds)
                        response = await self.get_user_input_with_timeout(30)
                        
                        if response:
                            response = response.strip().upper()
                            logger.info(f"[{port}] User response: {response}")
                            
                            # Send response to ESP32
                            await loop.run_in_executor(
                                None, lambda: ser.write((response + "\n").encode("utf-8"))
                            )
                            
                            if response == 'Y' or response == 'YES':
                                logger.info(f"[{port}] ✅ Pairing accepted - waiting for confirmation...")
                                
                                # ==================== CONFIGURATION PROMPTS ====================
                                # Wait for pairing to complete
                                await asyncio.sleep(2)
                                
                                # Ask about Device ID update
                                print(f"\n>>> Do you want to update the Device ID for this device? (Y/N): ", end='', flush=True)
                                response_device_id = await self.get_user_input_with_timeout(30)
                                
                                if response_device_id and response_device_id.strip().upper() in ['Y', 'YES']:
                                    print(f">>> Enter new Device ID (1-255): ", end='', flush=True)
                                    new_device_id_input = await self.get_user_input_with_timeout(30)
                                    
                                    if new_device_id_input:
                                        try:
                                            new_device_id = int(new_device_id_input.strip())
                                            if 1 <= new_device_id <= 255:
                                                # Send config command
                                                config_cmd = {
                                                    "CONFIG_CMD": "SET_DEVICE_ID",
                                                    "Did": int(pairing_device_id) if pairing_device_id else new_device_id,
                                                    "DeviceId": new_device_id
                                                }
                                                await loop.run_in_executor(
                                                    None, lambda: ser.write((json.dumps(config_cmd) + "\n").encode("utf-8"))
                                                )
                                                logger.info(f"[{port}] 📤 Sent Device ID update: {new_device_id}")
                                                await asyncio.sleep(1)  # Wait for confirmation
                                            else:
                                                logger.error(f"[{port}] ❌ Invalid Device ID (must be 1-255)")
                                        except ValueError:
                                            logger.error(f"[{port}] ❌ Invalid Device ID format")
                                
                                # Ask about GPIO config update
                                print(f"\n>>> Do you want to update the GPIO configuration? (Y/N): ", end='', flush=True)
                                response_gpio = await self.get_user_input_with_timeout(30)
                                
                                if response_gpio and response_gpio.strip().upper() in ['Y', 'YES']:
                                    print("\n>>> Enter GPIO pin numbers:")
                                    
                                    gpio_prompts = [
                                        ("Red LED pin", "RedPin"),
                                        ("Green LED pin", "GreenPin"),
                                        ("Yellow LED pin", "YellowPin"),
                                        ("Button A pin", "ButtonA"),
                                        ("Button B pin", "ButtonB"),
                                        ("Button C pin", "ButtonC"),
                                        ("Button D pin", "ButtonD")
                                    ]
                                    
                                    gpio_config = {
                                        "CONFIG_CMD": "SET_GPIO_CONFIG",
                                        "Did": int(pairing_device_id) if pairing_device_id else 0
                                    }
                                    
                                    all_valid = True
                                    for prompt, key in gpio_prompts:
                                        print(f">>> {prompt}: ", end='', flush=True)
                                        pin_input = await self.get_user_input_with_timeout(30)
                                        
                                        if pin_input:
                                            try:
                                                pin_num = int(pin_input.strip())
                                                if 0 <= pin_num <= 48:  # ESP32 GPIO range
                                                    gpio_config[key] = pin_num
                                                else:
                                                    logger.error(f"[{port}] ❌ Invalid pin number (must be 0-48)")
                                                    all_valid = False
                                                    break
                                            except ValueError:
                                                logger.error(f"[{port}] ❌ Invalid pin format")
                                                all_valid = False
                                                break
                                        else:
                                            logger.error(f"[{port}] ⏱️  Timeout waiting for pin input")
                                            all_valid = False
                                            break
                                    
                                    if all_valid:
                                        # Send GPIO config command
                                        await loop.run_in_executor(
                                            None, lambda: ser.write((json.dumps(gpio_config) + "\n").encode("utf-8"))
                                        )
                                        logger.info(f"[{port}] 📤 Sent GPIO configuration update")
                                        logger.info(f"[{port}] 🔄 Device will reboot to apply changes...")
                                        await asyncio.sleep(1)
                                        
                                # WiFi config update (NEW!)
                                print(f"\n>>> Update WiFi credentials? (Y/N): ", end='', flush=True)
                                response_wifi = await self.get_user_input_with_timeout(30)

                                if response_wifi and response_wifi.strip().upper() in ['Y', 'YES']:
                                    print(f">>> Enter WiFi SSID: ", end='', flush=True)
                                    wifi_ssid = await self.get_user_input_with_timeout(60)
                                    
                                    if wifi_ssid:
                                        print(f">>> Enter WiFi Password: ", end='', flush=True)
                                        wifi_password = await self.get_user_input_with_timeout(60)
                                        
                                        if wifi_password:
                                            wifi_config = {
                                                "CONFIG_CMD": "SET_WIFI_CONFIG",
                                                "Did": device_id,
                                                "SSID": wifi_ssid.strip(),
                                                "Password": wifi_password.strip()
                                            }
                                            
                                            ser.write((json.dumps(wifi_config) + "\n").encode("utf-8"))
                                            logger.info(f"📤 Sent WiFi config")
                            else:
                                logger.info(f"[{port}] ❌ Pairing rejected")
                        else:
                            logger.info(f"[{port}] ⏱️  No response - letting device timeout")
                        
                        # Exit pairing mode and set cooldown to ignore residual pairing messages
                        in_pairing_mode = False
                        pairing_cooldown_until = time.time() + 5  # 5 second cooldown
                        pairing_device_id = None
                        pairing_mac = None
                        continue
                    
                    # ==================== NORMAL MESSAGE PROCESSING ====================
                    
                    # Skip non-JSON lines (debug output from ESP32)
                    if not line.startswith("{"):
                        continue
                    
                    # Parse JSON payload
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    
                    # ==================== OTA STATUS HANDLING ====================
                    if "OTA" in payload:
                        self.handle_wifi_ota_status(payload)
                        continue
                    
                    # ==================== CONFIG STATUS HANDLING ====================
                    if "CONFIG" in payload:
                        config_status = payload.get("CONFIG")
                        device_id = payload.get("Did")
                        
                        if config_status == "DEVICE_ID_OK":
                            logger.info(f"✅ Device {device_id} - Device ID updated successfully")
                        elif config_status == "GPIO_OK":
                            logger.info(f"✅ Device {device_id} - GPIO config updated, device rebooting...")
                        elif config_status == "WIFI_OK":
                            logger.info(f"✅ Device {device_id} - WiFi credentials saved")
                        continue
                    
                    # ==================== NORMAL ANSWER HANDLING ====================
                    if "Ans" in payload or "Id" in payload:
                        user_id = payload.get('Id', 'unknown')
                        device_id = payload.get('Did', 'unknown')
                        answer = payload.get('Ans', 'unknown')                        
                        logger.info(f"⚡ User {user_id} {device_id} → '{answer}'")
                        await self.process_answer(payload, ser, loop)
                    
                except Exception as e:
                    if self.running:
                        logger.error(f"[{port}] Error processing message: {e}")
                    await asyncio.sleep(0.1)
        
        except Exception as e:
            logger.error(f"[{port}] Handler error: {e}")
        finally:
            # Cleanup
            if port in self.serial_ports:
                try:
                    self.serial_ports[port].close()
                except:
                    pass
                del self.serial_ports[port]
            logger.info(f"[{port}] Handler stopped")
    
    async def process_answer(self, payload: dict, ser: serial.Serial, loop):
        """Process answer from device and send to API"""
        try:
            # Add session ID
            payload_with_session = payload.copy()
            payload_with_session['sessionId'] = self.session_id
            
            # Determine URL based on presence of DeviceId
            url = API_URL
            if 'Did' in payload:
                url += f"?deviceId={payload['Did']}"
            
            # Send to API
            async with self.session.post(url, json=payload_with_session) as resp:
                response_text = await resp.text()
                
                if resp.status == 200:
                    response_data = json.loads(response_text)
                    self.stats['answers_processed'] += 1
                    
                    # Send response back to device
                    await self.send_device_response(ser, payload, response_data, loop)
                    
                    logger.debug(f"✅ Processed answer from Device {payload.get('Did', 'unknown')}")
                    
                else:
                    logger.error(f"❌ API error {resp.status}: {response_text}")
                    self.stats['errors'] += 1
                    
        except Exception as e:
            logger.error(f"❌ API call failed: {e}")
            self.stats['errors'] += 1
    
    async def send_device_response(self, ser: serial.Serial, original_payload: dict, 
                                 api_response: dict, loop):
        """Send response back to device"""
        try:
            terminal_id = original_payload.get("Id", "unknown")
            device_id = original_payload.get("Did", 0)
            
            response_packet = {
                "Id": terminal_id if terminal_id != "unknown" else api_response.get("id", 0),
                "c": api_response.get("code", 0),
                "Did": device_id
            }
            
            response_json = json.dumps(response_packet) + "\n"
            
            # Write back to serial
            await loop.run_in_executor(
                None, lambda: ser.write(response_json.encode("utf-8"))
            )
            
        except Exception as e:
            logger.error(f"❌ Failed to send device response: {e}")
    
    async def fetch_session_from_mother_id(self, mother_id: int) -> str:
        """Fetch session ID from API"""
        try:
            url = f"{MOTHER_URL}?motherId={mother_id}"
            async with self.session.post(url) as resp:
                response_data = await resp.json()
                
                if response_data.get("code") == 200:
                    return str(response_data.get("sessionId"))
                else:
                    logger.error(f"❌ Failed to fetch session: {response_data}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Mother API error: {e}")
            return None
        
    async def get_mother(self):
        session_id = await self.fetch_session_from_mother_id(MOTHER_ID)
        if session_id:
            self.session_id = session_id
            logger.info(f"✅ Session updated: {session_id}")
    
    # ==================== CLI INTERFACE ====================
    
    async def cli_handler(self):
        """Handle CLI commands for OTA updates"""
        logger.info("\n" + "="*60)
        logger.info("📟 CLI INTERFACE READY")
        logger.info("="*60)
        logger.info("Commands:")
        logger.info("  ota <device_id> <firmware_path_or_url>  - Start OTA update")
        logger.info("  status                                  - Show OTA status")
        logger.info("  stats                                   - Show statistics")
        logger.info("  help                                    - Show this help")
        logger.info("="*60 + "\n")
        
        loop = asyncio.get_event_loop()
        
        while self.running:
            try:
                # Non-blocking input read
                cmd = await loop.run_in_executor(None, input, ">>> ")
                cmd = cmd.strip()
                
                if not cmd:
                    continue
                
                parts = cmd.split()
                command = parts[0].lower()
                
                if command == "ota" and len(parts) >= 3:
                    try:
                        device_id = int(parts[1])
                        firmware_source = parts[2]
                        
                        # Find first available port
                        if not self.serial_ports:
                            logger.error("❌ No serial ports available")
                            continue
                        
                        port = list(self.serial_ports.keys())[0]
                        logger.info(f"🚀 Starting OTA update for Device {device_id}")
                        await self.initiate_wifi_ota(device_id, firmware_source, port)
                        self.stats['ota_updates'] += 1
                        
                    except ValueError:
                        logger.error("❌ Invalid device ID (must be integer)")
                    except Exception as e:
                        logger.error(f"❌ OTA command error: {e}")
                
                elif command == "status":
                    self.print_ota_status()
                
                elif command == "stats":
                    self.print_statistics()
                
                elif command == "help":
                    logger.info("\nCommands:")
                    logger.info("  ota <device_id> <firmware_path_or_url>  - Start OTA update")
                    logger.info("  status                                  - Show OTA status")
                    logger.info("  stats                                   - Show statistics")
                    logger.info("  help                                    - Show this help\n")
                
                else:
                    logger.warning(f"❌ Unknown command: {command}")
                    logger.info("Type 'help' for available commands")
                
            except Exception as e:
                if self.running:
                    logger.error(f"CLI error: {e}")
                await asyncio.sleep(0.1)
    
    def print_ota_status(self):
        """Print current OTA status"""
        if not self.ota_sessions:
            logger.info("📊 No active OTA sessions")
            return
        
        logger.info("\n" + "="*60)
        logger.info("📊 OTA STATUS")
        logger.info("="*60)
        
        for device_id, session in self.ota_sessions.items():
            progress = (session.bytes_sent / session.firmware_size * 100) if session.firmware_size > 0 else 0
            elapsed = time.time() - session.start_time
            
            logger.info(f"\nDevice {device_id}:")
            logger.info(f"  Status: {session.status.value}")
            logger.info(f"  Progress: {progress:.1f}% ({session.bytes_sent}/{session.firmware_size} bytes)")
            logger.info(f"  Elapsed: {elapsed:.1f}s")
            if session.error_message:
                logger.info(f"  Error: {session.error_message}")
        
        logger.info("="*60 + "\n")
    
    def print_statistics(self):
        """Print system statistics"""
        uptime = time.time() - self.stats['start_time']
        answers_per_sec = self.stats['answers_processed'] / uptime if uptime > 0 else 0
        
        logger.info("\n" + "="*60)
        logger.info("📊 STATISTICS")
        logger.info("="*60)
        logger.info(f"Uptime: {uptime:.0f}s")
        logger.info(f"Answers Processed: {self.stats['answers_processed']}")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info(f"Answer Rate: {answers_per_sec:.2f}/sec")
        logger.info(f"OTA Updates Started: {self.stats['ota_updates']}")
        logger.info(f"OTA Successes: {self.stats['ota_successes']}")
        logger.info(f"OTA Failures: {self.stats['ota_failures']}")
        logger.info(f"Active Serial Ports: {len(self.serial_ports)}")
        logger.info(f"Active OTA Sessions: {len(self.ota_sessions)}")
        logger.info("="*60 + "\n")
            
    async def monitor_devices(self):
        """Monitor all devices"""
        logger.info("🔍 Starting device monitor...")
        
        last_stats_time = time.time()
        
        # Create OTA command file path (platform-independent)
        import tempfile
        temp_dir = tempfile.gettempdir()
        
        while self.running:
            try:
                # Check for OTA command files (support multiple devices)
                # Check both single file and per-device files
                ota_files = []
                
                # Single device trigger
                single_file = os.path.join(temp_dir, "esp_ota_command.json")
                if os.path.exists(single_file):
                    ota_files.append(single_file)
                
                # Multi-device triggers (esp_ota_command_7.json, esp_ota_command_8.json, etc.)
                import glob
                pattern = os.path.join(temp_dir, "esp_ota_command_*.json")
                ota_files.extend(glob.glob(pattern))
                
                # Process all trigger files
                for ota_cmd_file in ota_files:
                    try:
                        with open(ota_cmd_file, 'r') as f:
                            ota_cmd = json.load(f)
                        
                        # Remove file immediately
                        os.remove(ota_cmd_file)
                        
                        # Process OTA command
                        if 'device_id' in ota_cmd and 'firmware' in ota_cmd:
                            device_id = ota_cmd['device_id']
                            firmware = ota_cmd['firmware']
                            
                            # Find first available port
                            if self.serial_ports:
                                port = list(self.serial_ports.keys())[0]
                                logger.info(f"🚀 OTA trigger detected for Device {device_id}")
                                
                                # Start OTA in background (non-blocking for multiple devices)
                                asyncio.create_task(self.initiate_wifi_ota(device_id, firmware, port))
                                self.stats['ota_updates'] += 1
                                
                                # Small delay to avoid overwhelming the system
                                await asyncio.sleep(0.5)
                            else:
                                logger.error("❌ No serial ports available for OTA")
                    except Exception as e:
                        logger.error(f"❌ Error processing OTA command file: {e}")
                        try:
                            os.remove(ota_cmd_file)
                        except:
                            pass
                
                current_ports = self.find_esp32_ports()
                active_ports = set(self.active_devices.keys())
                
                # Start new devices
                new_ports = current_ports - active_ports
                for port in new_ports:
                    logger.info(f"📱 New device: {port}")
                    task = asyncio.create_task(self.handle_device(port))
                    self.active_devices[port] = task
                
                # Clean up disconnected devices
                disconnected_ports = active_ports - current_ports
                for port in disconnected_ports:
                    logger.info(f"📱 Disconnected: {port}")
                    task = self.active_devices.pop(port, None)
                    if task:
                        task.cancel()
                
                # Restart crashed handlers
                for port, task in list(self.active_devices.items()):
                    if task.done():
                        self.active_devices.pop(port)
                        if port in current_ports:
                            logger.info(f"🔄 Restarting handler: {port}")
                            new_task = asyncio.create_task(self.handle_device(port))
                            self.active_devices[port] = new_task
                
                # Performance reporting
                current_time = time.time()
                if current_time - last_stats_time > 360:  # Every 6 minutes
                    uptime = current_time - self.stats['start_time']
                    answers_per_sec = self.stats['answers_processed'] / uptime if uptime > 0 else 0
                    
                    logger.info(
                        f"📊 STATS: Answers: {self.stats['answers_processed']} | "
                        f"Errors: {self.stats['errors']} | "
                        f"OTA: {self.stats['ota_successes']}/{self.stats['ota_updates']} | "
                        f"Rate: {answers_per_sec:.1f}/sec"
                    )
                    last_stats_time = current_time
                
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(5)
    
    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("🛑 Shutting down...")
        self.running = False
        
        # Cancel all device handlers
        for task in self.active_devices.values():
            task.cancel()
        
        # Close serial ports
        for ser in self.serial_ports.values():
            try:
                ser.close()
            except:
                pass
        
        # Close HTTP session
        if self.session:
            await self.session.close()
        
        # Final stats
        uptime = time.time() - self.stats['start_time']
        answers_per_sec = self.stats['answers_processed'] / uptime if uptime > 0 else 0
        
        logger.info(
            f"📊 FINAL STATS: Answers: {self.stats['answers_processed']} | "
            f"Errors: {self.stats['errors']} | "
            f"OTA: {self.stats['ota_successes']}/{self.stats['ota_updates']} | "
            f"Avg Rate: {answers_per_sec:.1f}/sec"
        )
        
        logger.info("✅ Enhanced listener shutdown complete")

async def main():
    """Main entry point"""
    print("🎯 ESP32 Enhanced Listener - WITH OTA UPDATE SUPPORT")
    print("=" * 65)
    print("💡 Works with your existing receiver + child setup")
    print("🤝 Seamless pairing integration")
    print("🔄 OTA updates via GitHub URLs or local files")
    print("⚡ Simple and reliable processing")
    print("📊 Performance monitoring")
    print("=" * 65)
    
    async with FinalESP32Manager("0") as manager:
        try:
            ports = manager.find_esp32_ports()
            if ports:
                logger.info(f"📱 Found {len(ports)} devices: {list(ports)}")
            else:
                logger.info("💡 Waiting for mother device...")
            
            print("\n🎯 READY FOR 40 DEVICES + OTA UPDATES")
            print("   • Seamless pairing support")
            print("   • Interactive pairing prompts")
            print("   • Config updates during pairing")
            print("   • File-based OTA trigger")
            print("   • Stats every 6 minutes")
            print("   • Ctrl+C to stop")
            print("\n💡 TO TRIGGER OTA UPDATE:")
            print("   Create file: /tmp/esp_ota_command.json")
            print("   Content: {")
            print('     "device_id": 7,')
            print('     "firmware": "https://github.com/.../firmware.bin"')
            print("   }")
            print("   Or: {")
            print('     "device_id": 7,')
            print('     "firmware": "/path/to/firmware.bin"')
            print("   }")
            print("   File will be auto-deleted after processing\n")
            
            # Fetch session from API
            await manager.get_mother()
            
            # Start monitoring devices (pairing handled within handle_device)
            # CLI commands removed to prevent input conflicts with pairing
            await manager.monitor_devices()
            
        except KeyboardInterrupt:
            logger.info("🛑 Stopped by user")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Enhanced listener stopped")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)
