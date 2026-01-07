// Include WiFi Library
#include <WiFi.h>
#include <esp_now.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <esp_sleep.h>
#include <driver/rtc_io.h>
#include <Update.h>
#include <esp_ota_ops.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

#define BTN_DEBOUNCE_MS 500
unsigned long lastPressTime[4] = {0, 0, 0, 0};

// Default receiver MAC (can be changed via pairing)
uint8_t receiverMAC[6] = {0x88, 0x57, 0x21, 0xAD, 0xEE, 0xE0};

// GPIO Configuration - now stored in preferences
struct GPIOConfig {
  int RED_PIN;
  int GREEN_PIN;
  int YELLOW_PIN;
  int rowPins[4];
};

// Default GPIO configuration
GPIOConfig gpioConfig = {
  9,  // RED_PIN
  7,  // GREEN_PIN
  8,  // YELLOW_PIN
  {3, 2, 5, 4}  // rowPins: D2, D1, D4, D3
};

// Membrane keypad setup
char keyMap[4] = {'A', 'B', 'C', 'D'};

// WiFi Configuration - stored in preferences
struct WiFiConfig {
  char ssid[64];
  char password[64];
};

struct OTAConfig {
  bool pending;
  char firmwareURL[256];
};

OTAConfig otaConfig = {false, ""};

WiFiConfig wifiConfig = {"", ""};  // Empty by default
// Pairing mode settings
#define PAIRING_TIMEOUT_MS 30000  // 30 seconds in pairing mode
#define PAIRING_BROADCAST_INTERVAL_MS 1000  // Broadcast every 1 second
int dButtonPressCount = 0;
unsigned long lastDPressTime = 0;
#define D_PRESS_WINDOW_MS 3000  // 3 seconds window to press D 4 times
bool inPairingMode = false;
unsigned long pairingModeStartTime = 0;
unsigned long lastPairingBroadcast = 0;

// Power management settings
#define IDLE_TIMEOUT_MS 180000           // 3 minutes idle before warning
#define WARNING_PERIOD_MS 10000          // 10 seconds warning period
#define WARNING_BLINK_INTERVAL_MS 2000   // Blink every 2 seconds during warning
unsigned long lastActivityTime = 0;
unsigned long lastWarningBlinkTime = 0;
bool inWarningPeriod = false;
bool warningLedState = false;

// Deep sleep wake settings
#define WAKE_ACTION_TIMEOUT_MS 5000  // 5 seconds after wake to complete action before sleeping again
bool justWokeUp = false;
char wakeUpButton = '\0';

// WiFi OTA settings
bool otaInProgress = false;
size_t otaUpdateSize = 0;
size_t otaBytesReceived = 0;
unsigned long otaStartTime = 0;
#define OTA_TIMEOUT_MS 300000  // 5 minutes for WiFi OTA
#define WIFI_CONNECT_TIMEOUT_MS 30000  // 15 seconds to connect to WiFi
uint8_t expectedOTAMotherMAC[6] = {0};  // MAC that initiated OTA

// Preferences for persistent storage
Preferences prefs;
int userId = 0;  // Volatile - resets on boot, assigned by server each session
int deviceId = 29;  // Now loaded from preferences with default fallback
char currentValue = 'A';

bool waitingForResponse = false;
unsigned long lastSendTime = 0;
#define RESPONSE_TIMEOUT_MS 5000  // 5 seconds to account for 40 devices + server round trip
int currentSendAttempt = 0;

// ==================== PREFERENCES MANAGEMENT ====================
void loadDeviceId() {
  prefs.begin("buzzer", false);
  
  if (prefs.isKey("deviceId")) {
    deviceId = prefs.getInt("deviceId", 21);
    Serial.print("📱 Loaded Device ID: ");
    Serial.println(deviceId);
  } else {
    Serial.print("ℹ️  No saved Device ID, using default: ");
    Serial.println(deviceId);
    // Save default
    prefs.putInt("deviceId", deviceId);
  }
  
  prefs.end();
}

void saveDeviceId(int newDeviceId) {
  prefs.begin("buzzer", false);
  prefs.putInt("deviceId", newDeviceId);
  prefs.end();
  
  deviceId = newDeviceId;
  Serial.print("💾 Saved new Device ID: ");
  Serial.println(deviceId);
}

void loadGPIOConfig() {
  prefs.begin("buzzer", false);
  
  if (prefs.isKey("gpioConfig")) {
    size_t len = prefs.getBytes("gpioConfig", &gpioConfig, sizeof(GPIOConfig));
    if (len == sizeof(GPIOConfig)) {
      Serial.println("🔧 Loaded GPIO configuration from preferences");
    } else {
      Serial.println("⚠️  Invalid GPIO config, using defaults");
    }
  } else {
    Serial.println("ℹ️  No saved GPIO config, using defaults");
    // Save defaults
    prefs.putBytes("gpioConfig", &gpioConfig, sizeof(GPIOConfig));
  }
  
  prefs.end();
  
  Serial.print("   RED: GPIO");
  Serial.print(gpioConfig.RED_PIN);
  Serial.print(" | GREEN: GPIO");
  Serial.print(gpioConfig.GREEN_PIN);
  Serial.print(" | YELLOW: GPIO");
  Serial.println(gpioConfig.YELLOW_PIN);
  Serial.print("   BUTTONS: GPIO");
  for (int i = 0; i < 4; i++) {
    Serial.print(gpioConfig.rowPins[i]);
    if (i < 3) Serial.print(", GPIO");
  }
  Serial.println();
}

void saveGPIOConfig(GPIOConfig newConfig) {
  prefs.begin("buzzer", false);
  prefs.putBytes("gpioConfig", &newConfig, sizeof(GPIOConfig));
  prefs.end();
  
  gpioConfig = newConfig;
  Serial.println("💾 Saved new GPIO configuration");
}

void loadWiFiConfig() {
  prefs.begin("buzzer", false);
  
  if (prefs.isKey("wifiSSID") && prefs.isKey("wifiPass")) {
    prefs.getString("wifiSSID", wifiConfig.ssid, sizeof(wifiConfig.ssid));
    prefs.getString("wifiPass", wifiConfig.password, sizeof(wifiConfig.password));
    
    if (strlen(wifiConfig.ssid) > 0) {
      Serial.println("📡 Loaded WiFi credentials:");
      Serial.print("   SSID: ");
      Serial.println(wifiConfig.ssid);
      Serial.println("   Password: ********");
    } else {
      Serial.println("ℹ️  No WiFi credentials saved");
    }
  } else {
    Serial.println("ℹ️  No WiFi credentials saved");
  }
  
  prefs.end();
}

void saveWiFiConfig(const char* ssid, const char* password) {
  prefs.begin("buzzer", false);
  prefs.putString("wifiSSID", ssid);
  prefs.putString("wifiPass", password);
  prefs.end();
  
  strncpy(wifiConfig.ssid, ssid, sizeof(wifiConfig.ssid) - 1);
  strncpy(wifiConfig.password, password, sizeof(wifiConfig.password) - 1);
  
  Serial.println("💾 Saved WiFi credentials");
  Serial.print("   SSID: ");
  Serial.println(wifiConfig.ssid);
  Serial.println("   Password: ********");
}


// ==================== RGB LED FUNCTIONS ====================
void setColor(bool red, bool green, bool yellow) {
  digitalWrite(gpioConfig.RED_PIN, red ? HIGH : LOW);
  digitalWrite(gpioConfig.GREEN_PIN, green ? HIGH : LOW);
  digitalWrite(gpioConfig.YELLOW_PIN, yellow ? HIGH : LOW);
}

void colorOff() {
  setColor(false, false, false);
}

void colorRed() {
  setColor(true, false, false);
}

void colorGreen() {
  setColor(false, true, false);
}

void colorYellow() {
  setColor(false, false, true);
}

// ==================== MOTHER MAC MANAGEMENT ====================
void printMAC(uint8_t* mac) {
  for (int i = 0; i < 6; i++) {
    Serial.printf("%02X", mac[i]);
    if (i < 5) Serial.print(":");
  }
  Serial.println();
}

void loadMotherMAC() {
  prefs.begin("buzzer", false);
  
  // Try to load saved MAC
  if (prefs.isKey("motherMAC")) {
    size_t len = prefs.getBytes("motherMAC", receiverMAC, 6);
    if (len == 6) {
      Serial.print("📡 Loaded mother MAC: ");
      printMAC(receiverMAC);
    } else {
      Serial.println("⚠️  Invalid saved MAC, using default");
    }
  } else {
    Serial.println("ℹ️  No saved MAC, using default");
  }
  
  prefs.end();
}

void saveMotherMAC(uint8_t* mac) {
  prefs.begin("buzzer", false);
  prefs.putBytes("motherMAC", mac, 6);
  prefs.end();
  
  Serial.print("💾 Saved new mother MAC: ");
  printMAC(mac);
}

// ==================== WIFI OTA FUNCTIONS ====================
void saveOTAPending(const char* url) {
  prefs.begin("buzzer", false);
  prefs.putBool("otaPending", true);
  prefs.putString("otaURL", url);
  prefs.end();
  
  Serial.println("💾 Saved OTA pending");
  Serial.print("   URL: ");
  Serial.println(url);
}

void loadOTAPending() {
  prefs.begin("buzzer", false);
  otaConfig.pending = prefs.getBool("otaPending", false);
  if (otaConfig.pending) {
    prefs.getString("otaURL", otaConfig.firmwareURL, sizeof(otaConfig.firmwareURL));
    Serial.println("📋 OTA pending detected!");
    Serial.print("   URL: ");
    Serial.println(otaConfig.firmwareURL);
  }
  prefs.end();
}

void clearOTAPending() {
  prefs.begin("buzzer", false);
  prefs.putBool("otaPending", false);
  prefs.putString("otaURL", "");
  prefs.end();
  Serial.println("🧹 Cleared OTA pending");
}

bool connectToWiFi() {
  if (strlen(wifiConfig.ssid) == 0) {
    Serial.println("❌ No WiFi credentials configured");
    return false;
  }
  
  Serial.println("📡 Connecting to WiFi...");
  Serial.print("   SSID: ");
  Serial.println(wifiConfig.ssid);
  
  // Simple WiFi connection (no ESP-NOW to conflict with!)
  WiFi.mode(WIFI_STA);
  WiFi.begin(wifiConfig.ssid, wifiConfig.password);
  
  Serial.println("🔍 Waiting for connection...");
  int attempts = 0;
  unsigned long startTime = millis();
  
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - startTime > WIFI_CONNECT_TIMEOUT_MS) {
      Serial.println("❌ WiFi connection timeout");
      Serial.printf("   Final status: %d\n", WiFi.status());
      return false;
    }
    
    if (millis() - startTime > attempts * 2000) {
      Serial.printf("   Status: %d (attempt %d)\n", WiFi.status(), attempts);
      attempts++;
    }
    
    colorYellow();
    delay(250);
    colorOff();
    delay(250);
  }
  
  Serial.println("\n✅ WiFi connected!");
  Serial.print("📡 IP Address: ");
  Serial.println(WiFi.localIP());
  
  return true;
}

void disconnectWiFi() {
  WiFi.disconnect();
  
  // Re-initialize ESP-NOW
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(WIFI_PS_MIN_MODEM);
  
  if (esp_now_init() == ESP_OK) {
    Serial.println("✅ ESP-NOW re-initialized");
    
    // Re-add mother as peer
    esp_now_peer_info_t peerInfo = {};
    memcpy(peerInfo.peer_addr, receiverMAC, 6);
    peerInfo.channel = 0;
    peerInfo.encrypt = false;
    
    if (esp_now_add_peer(&peerInfo) == ESP_OK) {
      Serial.println("✅ Mother peer re-added");
    }
  }
}

void sendOTAStatus(const char* status, const char* message) {
  char response[128];
  snprintf(response, sizeof(response), 
           "{\"Did\":%d,\"OTA\":\"%s\",\"Msg\":\"%s\"}", 
           deviceId, status, message);
  
  // Try to send via ESP-NOW (might fail if WiFi connected)
  //esp_now_send(receiverMAC, (uint8_t*)response, strlen(response) + 1);
  
  Serial.print("📤 Status: ");
  Serial.println(response);
}

void performWiFiOTA(const char* firmwareURL) {
  otaInProgress = true;
  otaStartTime = millis();
  otaBytesReceived = 0;
  
  Serial.println("\n╔════════════════════════════════════╗");
  Serial.println("║   🔄 WiFi OTA UPDATE STARTING     ║");
  Serial.println("╚════════════════════════════════════╝");
  Serial.print("📥 Firmware URL: ");
  Serial.println(firmwareURL);
  
  // Show red LED during OTA
  colorRed();
  
  // Send OTA_STARTING status
  sendOTAStatus("OTA_STARTING", "Connecting to WiFi");
  
  // Connect to WiFi
  if (!connectToWiFi()) {
    sendOTAStatus("OTA_ERROR", "WiFi connection failed");
    colorRed();
    delay(2000);
    colorOff();
    otaInProgress = false;
    return;
  }
  
  // Download and flash firmware
  HTTPClient http;
  WiFiClientSecure client;
  client.setInsecure();  // Skip certificate verification (for GitHub raw URLs)
  
  Serial.println("📥 Starting firmware download...");
  sendOTAStatus("OTA_DOWNLOADING", "Downloading firmware");
  
  http.begin(client, firmwareURL);
  http.setTimeout(OTA_TIMEOUT_MS);
  
  int httpCode = http.GET();
  
  if (httpCode == HTTP_CODE_OK) {
    int contentLength = http.getSize();
    Serial.print("📦 Firmware size: ");
    Serial.print(contentLength);
    Serial.println(" bytes");
    
    if (contentLength > 0) {
      bool canBegin = Update.begin(contentLength);
      
      if (canBegin) {
        Serial.println("✅ OTA update started");
        sendOTAStatus("OTA_FLASHING", "Writing firmware");
        
        WiFiClient *stream = http.getStreamPtr();
        size_t written = 0;
        uint8_t buff[512] = { 0 };
        
        while (http.connected() && (written < contentLength)) {
          size_t available = stream->available();
          
          if (available) {
            int c = stream->readBytes(buff, ((available > sizeof(buff)) ? sizeof(buff) : available));
            
            if (Update.write(buff, c) != c) {
              Serial.println("❌ Write failed");
              Update.printError(Serial);
              break;
            }
            
            written += c;
            otaBytesReceived = written;
            
            // Progress indicator
            if (written % 10240 == 0 || written == contentLength) {
              int progress = (written * 100) / contentLength;
              Serial.print("📤 Progress: ");
              Serial.print(progress);
              Serial.print("% (");
              Serial.print(written);
              Serial.print("/");
              Serial.print(contentLength);
              Serial.println(" bytes)");
              
              // Blink LED
              if (progress % 10 == 0) {
                colorOff();
                delay(50);
                colorRed();
              }
            }
          }
          delay(1);
        }
        
        if (Update.end(true)) {
          Serial.println("\n✅ OTA UPDATE SUCCESS!");
          
          // Disconnect WiFi BEFORE rebooting for battery safety
          http.end();
          disconnectWiFi();
          
          // Clear OTA pending flag
          clearOTAPending();
          
          sendOTAStatus("OTA_SUCCESS", "Update complete, rebooting");
          
          // Green blinks
          for (int i = 0; i < 5; i++) {
            colorGreen();
            delay(200);
            colorOff();
            delay(200);
          }
          
          Serial.println("🔄 Rebooting in 3 seconds...");
          delay(3000);
          ESP.restart();
        } else {
          Serial.println("❌ OTA END FAILED!");
          Update.printError(Serial);
          sendOTAStatus("OTA_ERROR", "Flash end failed");
        }
      } else {
        Serial.println("❌ OTA BEGIN FAILED!");
        Update.printError(Serial);
        sendOTAStatus("OTA_ERROR", "Flash begin failed");
      }
    } else {
      Serial.println("❌ Invalid content length");
      sendOTAStatus("OTA_ERROR", "Invalid firmware size");
    }
  } else {
    Serial.print("❌ HTTP error: ");
    Serial.println(httpCode);
    sendOTAStatus("OTA_ERROR", "Download failed");
  }
  
  http.end();
  disconnectWiFi();
  
  // Red blinks on error
  for (int i = 0; i < 3; i++) {
    colorRed();
    delay(300);
    colorOff();
    delay(300);
  }
  
  otaInProgress = false;
}

// ==================== PAIRING MODE ====================
void enterPairingMode() {
  Serial.println("\n╔════════════════════════════════════╗");
  Serial.println("║   🔄 ENTERING PAIRING MODE        ║");
  Serial.println("╚════════════════════════════════════╝");
  Serial.println("📡 Broadcasting for 30 seconds...");
  Serial.println("💡 Listening for 'baby' response from new mother");
  
  inPairingMode = true;
  pairingModeStartTime = millis();
  lastPairingBroadcast = 0;
  
  // Green LED solid during pairing mode
  colorGreen();
}

void exitPairingMode() {
  Serial.println("❌ Pairing mode timeout - no mother found");
  inPairingMode = false;
  dButtonPressCount = 0;
  colorOff();
}

void broadcastPairingMessage() {
  char message[64];
  int len = snprintf(message, sizeof(message), "mother:%d", deviceId);
  
  // Broadcast to all (use broadcast MAC)
  uint8_t broadcastMAC[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
  
  // Temporarily add broadcast peer
  esp_now_peer_info_t broadcastPeer = {};
  memcpy(broadcastPeer.peer_addr, broadcastMAC, 6);
  broadcastPeer.channel = 0;
  broadcastPeer.encrypt = false;
  broadcastPeer.ifidx = WIFI_IF_STA;
  
  // Check if broadcast peer already exists
  if (!esp_now_is_peer_exist(broadcastMAC)) {
    esp_now_add_peer(&broadcastPeer);
  }
  
  // Send broadcast
  esp_err_t result = esp_now_send(broadcastMAC, (uint8_t *)message, len + 1);
  
  if (result == ESP_OK) {
    Serial.print("📡 Broadcasting: ");
    Serial.println(message);
  } else {
    Serial.print("❌ Broadcast failed (err ");
    Serial.print(result);
    Serial.println(")");
  }
}

void checkPairingMode() {
  if (!inPairingMode) return;
  
  unsigned long elapsed = millis() - pairingModeStartTime;
  
  // Check timeout
  if (elapsed >= PAIRING_TIMEOUT_MS) {
    exitPairingMode();
    return;
  }
  
  // Double-check we're still in pairing mode before broadcasting
  if (!inPairingMode) return;
  
  // Broadcast periodically
  if (millis() - lastPairingBroadcast >= PAIRING_BROADCAST_INTERVAL_MS) {
    broadcastPairingMessage();
    lastPairingBroadcast = millis();
    
    // Blink green every broadcast
    colorOff();
    delay(50);
    colorGreen();
  }
}

// ==================== ESP-NOW CALLBACKS ====================
void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
  if (!inPairingMode) {  // Don't spam during pairing
    Serial.print("Last packet: ");
    Serial.println(status == ESP_NOW_SEND_SUCCESS ? "Delivery success" : "Delivery fail");
  }
}

void OnDataRecv(const esp_now_recv_info *recv_info, const uint8_t *incomingData, int len) {
  lastActivityTime = millis();  // Reset activity timer on incoming message
  inWarningPeriod = false;      // Cancel warning if message received
  
  String msg = String((char*)incomingData);
  
  // ==================== WIFI OTA MESSAGE HANDLING ====================
  if (msg.startsWith("{") && msg.indexOf("\"OTA_CMD\"") > 0) {
    StaticJsonDocument<256> doc;
    DeserializationError error = deserializeJson(doc, msg);
    
    if (!error && doc.containsKey("OTA_CMD")) {
      const char* cmd = doc["OTA_CMD"];
      
      // Handle WiFi OTA command
      if (strcmp(cmd, "WIFI_UPDATE") == 0) {
        const char* firmwareURL = doc["URL"];
        
        if (firmwareURL && strlen(firmwareURL) > 0) {
          Serial.println("🔄 WiFi OTA command received!");
          Serial.print("📥 URL: ");
          Serial.println(firmwareURL);
          
          // Save to prefs and reboot
          saveOTAPending(firmwareURL);
          sendOTAStatus("OTA_STARTING", "Rebooting for OTA");
          
          Serial.println("🔄 Rebooting in 2 seconds...");
          delay(2000);
          ESP.restart();
        } else {
          Serial.println("❌ Invalid firmware URL");
          sendOTAStatus("OTA_ERROR", "Invalid URL");
        }
        return;
      }
    }
  }
    
  // ==================== PAIRING MESSAGE HANDLING ====================
  // Check for "baby" response during pairing mode
  if (inPairingMode && msg == "baby") {    
    Serial.print("📡 New mother MAC: ");
    printMAC((uint8_t*)recv_info->src_addr);
    
    // IMMEDIATELY exit pairing mode to stop any further broadcasts
    inPairingMode = false;
    dButtonPressCount = 0;
    
    // Save new mother MAC
    memcpy(receiverMAC, recv_info->src_addr, 6);
    saveMotherMAC(receiverMAC);
    
    // Remove old peer and add new one
    esp_now_del_peer(receiverMAC);  // Try to remove (may not exist)
    
    esp_now_peer_info_t peerInfo = {};
    memcpy(peerInfo.peer_addr, receiverMAC, 6);
    peerInfo.channel = 0;
    peerInfo.encrypt = false;
    peerInfo.ifidx = WIFI_IF_STA;
    
    if (esp_now_add_peer(&peerInfo) == ESP_OK) {      
      // Celebrate with green blinks
      for (int i = 0; i < 5; i++) {
        colorGreen();
        delay(200);
        colorOff();
        delay(200);
      }
    } else {
      Serial.println("❌ Failed to add new mother as peer");
      colorRed();
      delay(2000);
    }
    
    // Turn off LED and finish pairing
    colorOff();
    return;
  }
  
  // Normal message handling (not in pairing mode)
  if (inPairingMode) {
    return;  // Ignore other messages during pairing
  }
  
  colorOff();  // Turn off warning LED
  
  // ==================== CONFIGURATION MESSAGE HANDLING ====================
  // Check for configuration commands
  if (msg.startsWith("{") && msg.indexOf("\"CONFIG_CMD\"") > 0) {
    StaticJsonDocument<256> doc;
    DeserializationError error = deserializeJson(doc, msg);
    
    if (!error && doc.containsKey("CONFIG_CMD")) {
      const char* cmd = doc["CONFIG_CMD"];
      
      // Handle Device ID update
      if (strcmp(cmd, "SET_DEVICE_ID") == 0) {
        int newDeviceId = doc["DeviceId"] | 0;
        if (newDeviceId > 0 && newDeviceId <= 255) {
          Serial.print("🔧 Updating Device ID from ");
          Serial.print(deviceId);
          Serial.print(" to ");
          Serial.println(newDeviceId);
          
          saveDeviceId(newDeviceId);
          
          // Send confirmation
          char response[64];
          snprintf(response, sizeof(response), 
                   "{\"Did\":%d,\"CONFIG\":\"DEVICE_ID_OK\"}", newDeviceId);
          esp_now_send(receiverMAC, (uint8_t*)response, strlen(response) + 1);
          
          // Blink green to confirm
          for (int i = 0; i < 3; i++) {
            colorGreen();
            delay(200);
            colorOff();
            delay(200);
          }
          
          Serial.println("✅ Device ID updated successfully");
        } else {
          Serial.println("❌ Invalid Device ID (must be 1-255)");
        }
        return;
      }
      
      // Handle GPIO Config update
      else if (strcmp(cmd, "SET_GPIO_CONFIG") == 0) {
        Serial.println("🔧 Updating GPIO configuration...");
        
        GPIOConfig newConfig;
        newConfig.RED_PIN = doc["RedPin"] | gpioConfig.RED_PIN;
        newConfig.GREEN_PIN = doc["GreenPin"] | gpioConfig.GREEN_PIN;
        newConfig.YELLOW_PIN = doc["YellowPin"] | gpioConfig.YELLOW_PIN;
        newConfig.rowPins[0] = doc["ButtonA"] | gpioConfig.rowPins[0];
        newConfig.rowPins[1] = doc["ButtonB"] | gpioConfig.rowPins[1];
        newConfig.rowPins[2] = doc["ButtonC"] | gpioConfig.rowPins[2];
        newConfig.rowPins[3] = doc["ButtonD"] | gpioConfig.rowPins[3];
        
        Serial.print("   RED: GPIO");
        Serial.print(newConfig.RED_PIN);
        Serial.print(" | GREEN: GPIO");
        Serial.print(newConfig.GREEN_PIN);
        Serial.print(" | YELLOW: GPIO");
        Serial.println(newConfig.YELLOW_PIN);
        Serial.print("   BUTTONS: GPIO");
        for (int i = 0; i < 4; i++) {
          Serial.print(newConfig.rowPins[i]);
          if (i < 3) Serial.print(", GPIO");
        }
        Serial.println();
        
        saveGPIOConfig(newConfig);
        
        // Send confirmation
        char response[64];
        snprintf(response, sizeof(response), 
                 "{\"Did\":%d,\"CONFIG\":\"GPIO_OK\"}", deviceId);
        esp_now_send(receiverMAC, (uint8_t*)response, strlen(response) + 1);
        
        // Yellow blinks to confirm
        for (int i = 0; i < 3; i++) {
          colorYellow();
          delay(200);
          colorOff();
          delay(200);
        }
        
        // Reboot to apply new GPIO config
        Serial.println("✅ GPIO configuration saved");
        Serial.println("🔄 Rebooting in 3 seconds to apply changes...");
        delay(3000);
        ESP.restart();
        return;
      }

      // Handle WiFi Config update
      else if (strcmp(cmd, "SET_WIFI_CONFIG") == 0) {
        const char* ssid = doc["SSID"];
        const char* password = doc["Password"];
        
        if (ssid && password && strlen(ssid) > 0) {
          Serial.println("🔧 Updating WiFi configuration...");
          Serial.print("   SSID: ");
          Serial.println(ssid);
          
          saveWiFiConfig(ssid, password);
          
          // Send confirmation
          char response[64];
          snprintf(response, sizeof(response), 
                   "{\"Did\":%d,\"CONFIG\":\"WIFI_OK\"}", deviceId);
          esp_now_send(receiverMAC, (uint8_t*)response, strlen(response) + 1);
          
          // Green blinks
          for (int i = 0; i < 3; i++) {
            colorGreen();
            delay(200);
            colorOff();
            delay(200);
          }
          
          Serial.println("✅ WiFi credentials saved");
        }
        return;
      }
    }
  }
  
  // ==================== NORMAL MESSAGE HANDLING ====================
  
  if(msg == "r"){
    Serial.println("🔄 Retry requested by mother (message was malformed)");
    waitingForResponse = false;  // Clear waiting flag
    sendButton(currentValue);  
    return;  
  }
  
  StaticJsonDocument<256> doc;
  DeserializationError error = deserializeJson(doc, msg);

  if (error) return;
  Serial.println("\n✅ RECEIVED RESPONSE!");
  int code = doc["c"] | -1;  
  int id = doc["Id"] | -1;
  // const char* msgText = doc["msg"] | "";

  waitingForResponse = false;
  // Store userId temporarily in RAM (NOT persistent storage)
  // This allows the device to change hands - userId resets on reboot
  if (id != -1) {
    userId = id;
  }

  handleResponse(code);
}

void handleResponse(int code) {
  void (*colorFunc)() = colorYellow;
  int blinkCount = 3;
  int blinkDelay = 200;
  
  switch(code) {
    case 200:
      blinkCount = 3;
      blinkDelay = 200;
      colorFunc = colorGreen;
      break;
    case 201:
      blinkCount = 2;
      blinkDelay = 100;
      colorFunc = colorRed;
      break;
    case 300:
      blinkCount = 3;
      blinkDelay = 200;
      colorFunc = colorYellow;
      break;
    case 301:
      blinkCount = 3;
      blinkDelay = 100;
      colorFunc = colorYellow;
      break;
    default:
      blinkCount = 5;
      blinkDelay = 100;
      colorFunc = colorYellow;
      break;
  }
  
  for(int i = 0; i < blinkCount; i++) {
    colorFunc();
    delay(blinkDelay);
    colorOff();
    delay(blinkDelay);
  }
}

// ==================== POWER MANAGEMENT ====================
void configureWakeUp() {
  // Configure EXT1 wake-up on any of the keypad pins going LOW
  // Create bitmask for all row pins
  uint64_t wakeup_pin_mask = 0;
  
  for (int i = 0; i < 4; i++) {
    wakeup_pin_mask |= (1ULL << gpioConfig.rowPins[i]);
    
    // CRITICAL for ESP32-S3: Initialize RTC GPIO and enable pullup
    // This prevents spurious wake-ups
    rtc_gpio_init((gpio_num_t)gpioConfig.rowPins[i]);
    rtc_gpio_set_direction((gpio_num_t)gpioConfig.rowPins[i], RTC_GPIO_MODE_INPUT_ONLY);
    rtc_gpio_pullup_en((gpio_num_t)gpioConfig.rowPins[i]);      // Enable pullup
    rtc_gpio_pulldown_dis((gpio_num_t)gpioConfig.rowPins[i]);   // Disable pulldown
    rtc_gpio_hold_dis((gpio_num_t)gpioConfig.rowPins[i]);       // Disable hold
  }
  
  // Wake up when ANY pin goes LOW (button pressed)
  esp_sleep_enable_ext1_wakeup(wakeup_pin_mask, ESP_EXT1_WAKEUP_ANY_LOW);
  
  Serial.println("🛌 Wake-up configured:");
  Serial.println("   • Press any keypad button to wake");
  Serial.print("   • Wake pins: ");
  for (int i = 0; i < 4; i++) {
    Serial.print("GPIO");
    Serial.print(gpioConfig.rowPins[i]);
    if (i < 3) Serial.print(", ");
  }
  Serial.println();
}

void enterDeepSleep() {
  // CRITICAL: Never sleep during OTA!
  if (otaInProgress) {
    Serial.println("⚠️  Cannot sleep during OTA update!");
    return;
  }
  
  Serial.println("😴 Entering DEEP sleep...");
  Serial.println("🔘 Press any button to wake and send immediately");
  
  for(int i = 0; i < 5; i++) {
    colorYellow();
    delay(100);
    colorOff();
    delay(100);
  }
  
  colorOff();  // Ensure all LEDs are off
  
  // Deinitialize RTC GPIOs before sleep (re-configured on wake)
  for (int i = 0; i < 4; i++) {
    rtc_gpio_deinit((gpio_num_t)gpioConfig.rowPins[i]);
  }
  
  // Re-configure wakeup (this ensures fresh config)
  configureWakeUp();
  
  Serial.flush();
  esp_deep_sleep_start();
}

void checkPowerManagement() {
  // Don't sleep during pairing mode OR OTA update
  if (inPairingMode || otaInProgress) return;
  
  unsigned long idleTime = millis() - lastActivityTime;
  
  if (!inWarningPeriod && idleTime >= IDLE_TIMEOUT_MS) {
    Serial.println("⚠️  WARNING: 30 seconds until sleep!");
    Serial.println("💡 Press any button to stay awake");
    inWarningPeriod = true;
    lastWarningBlinkTime = millis();
    colorYellow();
    warningLedState = true;
  }
  
  if (inWarningPeriod) {
    if (idleTime >= (IDLE_TIMEOUT_MS + WARNING_PERIOD_MS)) {
      enterDeepSleep();
    }
    
    if (millis() - lastWarningBlinkTime >= WARNING_BLINK_INTERVAL_MS) {
      warningLedState = !warningLedState;
      if (warningLedState) {
        colorYellow();
      } else {
        colorOff();
      }
      lastWarningBlinkTime = millis();
      
      unsigned long remainingMs = (IDLE_TIMEOUT_MS + WARNING_PERIOD_MS) - idleTime;
      Serial.print("⏱️  Sleep in ");
      Serial.print(remainingMs / 1000);
      Serial.println(" seconds...");
    }
  }
}

void resetActivityTimer() {
  lastActivityTime = millis();
  if (inWarningPeriod) {
    inWarningPeriod = false;
    colorOff();
  }
}

// ==================== WAKE-UP HANDLER ====================
void lightUp() {
  colorGreen();
  delay(200);
  colorYellow();
  delay(200);
  colorRed();
  delay(200);
  colorOff();
}

void handleWakeUp() {
  // Check if we woke up from deep sleep
  esp_sleep_wakeup_cause_t wakeup_reason = esp_sleep_get_wakeup_cause();
  
  if (wakeup_reason == ESP_SLEEP_WAKEUP_EXT1) {
    Serial.println("👁️  Woke up from deep sleep!");
    
    // ===== FIX: Use the wake status register instead of reading pins =====
    // Get the GPIO wake status - this tells us which pin(s) triggered the wake
    uint64_t wakeup_pin_mask = esp_sleep_get_ext1_wakeup_status();
    
    Serial.print("🔍 Wake-up pin mask: 0x");
    Serial.println((uint32_t)wakeup_pin_mask, HEX);
    
    // Check which button corresponds to the wake-up pin
    for (int i = 0; i < 4; i++) {
      uint64_t pinMask = (1ULL << gpioConfig.rowPins[i]);
      if (wakeup_pin_mask & pinMask) {
        wakeUpButton = keyMap[i];
        justWokeUp = true;
        Serial.print("✅ Woken up by button: ");
        Serial.println(wakeUpButton);
        break;
      }
    }
    
    // If for some reason we didn't detect the wake button, check pins as fallback
    if (wakeUpButton == '\0') {
      Serial.println("⚠️  Wake status didn't match any button, checking pins...");
      delay(50);
      
      for (int i = 0; i < 4; i++) {
        if (digitalRead(gpioConfig.rowPins[i]) == LOW) {
          wakeUpButton = keyMap[i];
          justWokeUp = true;
          Serial.print("🔍 Detected button (fallback): ");
          Serial.println(wakeUpButton);
          break;
        }
      }
    }
  }
}

// ==================== SETUP ====================
void setup() {
  Serial.begin(115200);
  delay(100);
  
  Serial.println("🚀 Starting up...");
  
  // Load configuration from preferences FIRST
  loadDeviceId();
  loadGPIOConfig();
  loadWiFiConfig();
  loadOTAPending();
  // Setup RGB LED pins first (needed for wake-up blink)
  pinMode(gpioConfig.RED_PIN, OUTPUT);
  pinMode(gpioConfig.GREEN_PIN, OUTPUT);
  pinMode(gpioConfig.YELLOW_PIN, OUTPUT);
  colorOff();
  
  // Handle wake-up from deep sleep
  handleWakeUp();
  
  // Load saved mother MAC (persistent)
  loadMotherMAC();
  
  // userId is NOT loaded from preferences - it resets to 0 on each boot
  // Server will assign the current user based on deviceId
  userId = 0;
  
  Serial.print("📱 Device ID (Permanent): ");
  Serial.println(deviceId);
  
  lightUp();
  
  Serial.println("🎹 Setting up 1x4 membrane keypad...");
  
  for (int i = 0; i < 4; i++) {
    pinMode(gpioConfig.rowPins[i], INPUT_PULLUP);
  }

  
  // ==================== CHECK FOR PENDING OTA ====================
  if (otaConfig.pending) {
    Serial.println("\n╔════════════════════════════════════╗");
    Serial.println("║   🔄 OTA UPDATE PENDING           ║");
    Serial.println("╚════════════════════════════════════╝");
    
    // Perform OTA (WiFi only, no ESP-NOW initialized yet!)
    performWiFiOTA(otaConfig.firmwareURL);
    
    // If we get here, OTA failed - clear flag and continue normally
    clearOTAPending();
    Serial.println("⚠️  OTA failed, continuing with normal boot");
    delay(2000);
  }

  // Configure wake-up sources for deep sleep
  configureWakeUp();
  
  WiFi.mode(WIFI_STA);

  WiFi.setSleep(WIFI_PS_MIN_MODEM);
  
  if (esp_now_init() != ESP_OK) {
    Serial.println("❌ Error initializing ESP-NOW");
    colorRed();
    delay(2000);
    return;
  }
  
  esp_now_register_send_cb(OnDataSent);
  esp_now_register_recv_cb(OnDataRecv);

  // Add current mother as peer
  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, receiverMAC, 6);
  peerInfo.channel = 0;
  peerInfo.encrypt = false;
  peerInfo.ifidx = WIFI_IF_STA;
    
  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("❌ Failed to add peer");
    colorRed();
    delay(2000);
    return;
  }

  // If we just woke up and detected a button, send it immediately
  if (justWokeUp && wakeUpButton != '\0') {
    Serial.println("📤 Sending wake-up button press...");
    delay(100); // Small delay to ensure ESP-NOW is fully ready
    sendButton(wakeUpButton);
    Serial.print("🔢 Sending from wake: ");
    Serial.println(wakeUpButton);
    // Don't reset flags yet - will be handled in loop to prevent duplicate
  }

  Serial.println("\n💡 PAIRING MODE:");
  Serial.println("   • Press button D four times within 3 seconds");
  Serial.println("🔘 Ready for button presses!");
  Serial.println("🔄 OTA updates enabled (mother-authenticated)");
  
  delay(1000);
  colorOff();
  
  lastActivityTime = millis();
}

// ==================== MAIN LOOP ====================
void loop() {
  // Check pairing mode first
  checkPairingMode();
  
  // Check all keypad buttons
  for (int i = 0; i < 4; i++) {
    if (digitalRead(gpioConfig.rowPins[i]) == LOW) {
      if ((millis() - lastPressTime[i]) > BTN_DEBOUNCE_MS) {
        char pressedKey = keyMap[i];
        
        // Skip if this is the wake-up button press we already handled
        if (justWokeUp && pressedKey == wakeUpButton) {
          justWokeUp = false;
          wakeUpButton = '\0';
          lastPressTime[i] = millis();
          continue;
        }
        
        Serial.print("🔘 Key Pressed: ");
        Serial.println(pressedKey);
        
        // Check for D button pairing sequence
        if (pressedKey == 'D') {
          // Check if within the time window
          if (millis() - lastDPressTime < D_PRESS_WINDOW_MS) {
            dButtonPressCount++;
            Serial.print("🔢 D press count: ");
            Serial.println(dButtonPressCount);
            
            if (dButtonPressCount >= 4) {
              // Enter pairing mode!
              enterPairingMode();
              dButtonPressCount = 0;
            }
          } else {
            // Reset count if outside window
            dButtonPressCount = 1;
            Serial.println("🔢 D press count: 1 (reset)");
          }
          lastDPressTime = millis();
        } else {
          // Reset D count on other button press
          dButtonPressCount = 0;
        }
        
        // Normal button handling (unless in pairing mode or OTA)
        if (!inPairingMode && !otaInProgress) {
          resetActivityTimer();
          sendButton(pressedKey);
        }
        
        lastPressTime[i] = millis();
      }
    }
  }
  
  // Check power management (includes OTA check)
  checkPowerManagement();
  
  delay(100);
}

// ==================== SEND BUTTON ====================
void sendButton(char btn) {
  char message[64];
  int len;

  // ALWAYS send DeviceId
  // If userId is assigned, send both (server uses Id, Did helps with tracking)
  if (userId == 0) {
    // First message - only DeviceId (server will assign userId)
    len = snprintf(message, sizeof(message), "{\"Did\":%d,\"Ans\":\"%c\"}", deviceId, btn);
  } else {
    // Subsequent messages - send both userId and deviceId
    len = snprintf(message, sizeof(message), "{\"Id\":%d,\"Ans\":\"%c\"}", userId, btn);   
  }

  const int maxRetries = 3;
  esp_err_t result = ESP_FAIL;
  currentValue = btn;
  waitingForResponse = true;
  
  for (int attempt = 0; attempt < maxRetries; attempt++) {
    int jitter = random(10, 100 * (attempt + 1));
    delay(jitter);

    result = esp_now_send(receiverMAC, (uint8_t *)message, len + 1);
    
    if (result == ESP_OK) {
      waitingForResponse = true;
      colorYellow();
      Serial.println("✅ Send successful");
      break;
    } else {
      Serial.print("❌ Send failed (err ");
      Serial.print(result);
      Serial.println(")");
    }
  }

  delay(500);
  
  if (!inWarningPeriod) {
    colorOff();
  }
}
