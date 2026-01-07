#include <WiFi.h>
#include <esp_now.h>
#include <ArduinoJson.h>
#include <Preferences.h>

// Mother ID (permanent identifier for this receiver)
Preferences prefs;
const int MOTHER_ID = 1;  // Change this for each mother device (1, 2, 3, etc.)

// Message queue for handling ESP-NOW packets outside interrupt
#define MAX_QUEUE_SIZE 20
struct QueuedMessage {
  uint8_t mac[6];
  char data[250];
  int len;
  bool valid;
};
QueuedMessage messageQueue[MAX_QUEUE_SIZE];
int queueHead = 0;
int queueTail = 0;
volatile int queueCount = 0;

// Enhanced mapping to support both TerminalId and DeviceId
struct TerminalMap {
  int terminalId;    // -1 if not assigned yet
  int deviceId;      // Always present from first communication (integer)
  uint8_t mac[6];
  bool inOTAMode;    // Track if child is currently updating
  unsigned long otaStartTime;  // When OTA started
};
TerminalMap terminals[30];  // support up to 30 children
int terminalCount = 0;

// Pairing request tracking
struct PairingRequest {
  int deviceId;
  uint8_t mac[6];
  unsigned long timestamp;
  bool active;
};
PairingRequest pendingPairing = {0, {0}, 0, false};
#define PAIRING_PROMPT_TIMEOUT_MS 30000  // 30 seconds to respond

// OTA tracking
#define OTA_TIMEOUT_MS 420000  // 7 minutes for complete OTA (large firmware support)
int activeOTACount = 0;

// ==================== TERMINAL MANAGEMENT ====================
void addOrUpdateTerminalByDeviceId(int deviceId, const uint8_t* mac, int terminalId = -1) {
  // First check if device already exists by DeviceId
  for (int i = 0; i < terminalCount; i++) {
    if (terminals[i].deviceId == deviceId) {
      // Update existing entry
      memcpy(terminals[i].mac, mac, 6);
      if (terminalId != -1) {
        terminals[i].terminalId = terminalId;
        Serial.print("Updated Terminal ID for Device ");
        Serial.print(deviceId);
        Serial.print(" -> Terminal ID: ");
        Serial.println(terminalId);
      }
      return;
    }
  }
  
  // Device not found, add new entry
  if (terminalCount < 30) {
    terminals[terminalCount].deviceId = deviceId;
    terminals[terminalCount].terminalId = terminalId;
    memcpy(terminals[terminalCount].mac, mac, 6);
    terminals[terminalCount].inOTAMode = false;
    terminals[terminalCount].otaStartTime = 0;
    terminalCount++;
    
    Serial.print("Added new device: ");
    Serial.print(deviceId);
    if (terminalId != -1) {
      Serial.print(" with Terminal ID: ");
      Serial.println(terminalId);
    } else {
      Serial.println(" (Terminal ID pending)");
    }
  } else {
    Serial.println("Terminal capacity reached!");
  }
}

void addOrUpdateTerminalById(int terminalId, const uint8_t* mac) {
  // First try to update existing entry by TerminalId
  for (int i = 0; i < terminalCount; i++) {
    if (terminals[i].terminalId == terminalId) {
      memcpy(terminals[i].mac, mac, 6);
      Serial.print("Updated existing Terminal ID: ");
      Serial.println(terminalId);
      return;
    }
  }
  
  // Not found by TerminalId, add as new entry (legacy support)
  if (terminalCount < 30) {
    terminals[terminalCount].terminalId = terminalId;
    terminals[terminalCount].deviceId = -1;  // DeviceId unknown in legacy mode
    memcpy(terminals[terminalCount].mac, mac, 6);
    terminals[terminalCount].inOTAMode = false;
    terminals[terminalCount].otaStartTime = 0;
    terminalCount++;
    
    Serial.print("Added new Terminal ID: ");
    Serial.print(terminalId);
    Serial.println(" (DeviceId unknown - legacy mode)");
  } else {
    Serial.println("Terminal capacity reached! Cannot add new Terminal ID");
  }
}

uint8_t* findMacByTerminalId(int terminalId) {
  for (int i = 0; i < terminalCount; i++) {
    if (terminals[i].terminalId == terminalId) {
      return terminals[i].mac;
    }
  }
  return nullptr;
}

uint8_t* findMacByDeviceId(int deviceId) {
  for (int i = 0; i < terminalCount; i++) {
    if (terminals[i].deviceId == deviceId) {
      return terminals[i].mac;
    }
  }
  return nullptr;
}

void printTerminalMap() {
  Serial.println("=== Current Terminal Map ===");
  for (int i = 0; i < terminalCount; i++) {
    Serial.print("Device ID: ");
    Serial.print(terminals[i].deviceId);
    Serial.print(" | Terminal ID: ");
    if (terminals[i].terminalId == -1) {
      Serial.print("PENDING");
    } else {
      Serial.print(terminals[i].terminalId);
    }
    Serial.print(" | OTA: ");
    Serial.print(terminals[i].inOTAMode ? "YES" : "NO");
    Serial.print(" | MAC: ");
    for (int j = 0; j < 6; j++) {
      if (j > 0) Serial.print(":");
      Serial.printf("%02X", terminals[i].mac[j]);
    }
    Serial.println();
  }
  Serial.println("========================");
}

// ==================== OTA MANAGEMENT ====================
void setOTAMode(int deviceId, bool enabled) {
  for (int i = 0; i < terminalCount; i++) {
    if (terminals[i].deviceId == deviceId) {
      bool wasInOTA = terminals[i].inOTAMode;
      terminals[i].inOTAMode = enabled;
      
      if (enabled) {
        terminals[i].otaStartTime = millis();
        if (!wasInOTA) activeOTACount++;
        Serial.print("🔄 Device ");
        Serial.print(deviceId);
        Serial.println(" entered OTA mode");
      } else {
        terminals[i].otaStartTime = 0;
        if (wasInOTA) activeOTACount--;
        Serial.print("✅ Device ");
        Serial.print(deviceId);
        Serial.println(" exited OTA mode");
      }
      return;
    }
  }
}

bool isInOTAMode(int deviceId) {
  for (int i = 0; i < terminalCount; i++) {
    if (terminals[i].deviceId == deviceId) {
      return terminals[i].inOTAMode;
    }
  }
  return false;
}

void checkOTATimeouts() {
  unsigned long now = millis();
  for (int i = 0; i < terminalCount; i++) {
    if (terminals[i].inOTAMode) {
      if (now - terminals[i].otaStartTime > OTA_TIMEOUT_MS) {
        Serial.print("⏱️  OTA TIMEOUT for Device ");
        Serial.println(terminals[i].deviceId);
        
        // Send timeout notification to Python
        StaticJsonDocument<128> doc;
        doc["Did"] = terminals[i].deviceId;
        doc["OTA"] = "OTA_TIMEOUT";
        doc["Msg"] = "Mother timeout";
        
        String output;
        serializeJson(doc, output);
        Serial.println(output);
        
        // Clear OTA mode
        setOTAMode(terminals[i].deviceId, false);
      }
    }
  }
}

// ==================== PAIRING FUNCTIONS ====================
void handlePairingRequest(int deviceId, const uint8_t* mac) {
  Serial.println("\n╔════════════════════════════════════════════════╗");
  Serial.println("║   🔔 PAIRING REQUEST RECEIVED                 ║");
  Serial.println("╚════════════════════════════════════════════════╝");
  Serial.print("📱 Device ID: ");
  Serial.println(deviceId);
  Serial.print("📡 MAC Address: ");
  for (int i = 0; i < 6; i++) {
    Serial.printf("%02X", mac[i]);
    if (i < 5) Serial.print(":");
  }
  Serial.println();
  Serial.println("\n🤔 Do you want to become the mother for this device?");
  Serial.println("Type 'Y' or 'y' to accept, anything else to reject");
  Serial.print("⏱️  You have 30 seconds to respond: ");
  
  // Store pending pairing request
  pendingPairing.deviceId = deviceId;
  memcpy(pendingPairing.mac, mac, 6);
  pendingPairing.timestamp = millis();
  pendingPairing.active = true;
}

void sendBabyResponse(const uint8_t* targetMac) {
  // Add peer if not exists
  if (!esp_now_is_peer_exist(targetMac)) {
    esp_now_peer_info_t peerInfo = {};
    memcpy(peerInfo.peer_addr, targetMac, 6);
    peerInfo.channel = 0;
    peerInfo.encrypt = false;
    
    esp_err_t result = esp_now_add_peer(&peerInfo);
    if (result != ESP_OK) {
      Serial.println("❌ Failed to add peer for pairing");
      return;
    }
  }
  
  // Send "baby" response
  String response = "baby";
  esp_err_t result = esp_now_send(targetMac, (uint8_t*)response.c_str(), response.length());
  
  if (result == ESP_OK) {
    Serial.println("\n✅ Sent 'baby' response to child device!");
    Serial.println("🎉 Pairing successful - you are now the mother!");
    Serial.print("📡 Child MAC: ");
    for (int i = 0; i < 6; i++) {
      Serial.printf("%02X", targetMac[i]);
      if (i < 5) Serial.print(":");
    }
    Serial.println("\n");
  } else {
    Serial.print("❌ Failed to send 'baby' response. Error: ");
    Serial.println(result);
  }
}

void checkPairingTimeout() {
  if (!pendingPairing.active) return;
  
  unsigned long elapsed = millis() - pendingPairing.timestamp;
  
  if (elapsed >= PAIRING_PROMPT_TIMEOUT_MS) {
    Serial.println("\n\n⏱️  PAIRING REQUEST TIMED OUT - No response received");
    Serial.println("Device will continue broadcasting...\n");
    pendingPairing.active = false;
  }
}

// ==================== ESP-NOW CALLBACKS ====================
void sendRetryToChild(const uint8_t *mac) {
  String output = "r";
  Serial.printf("📤 Sending retry request to device\n");
  
  esp_err_t result = esp_now_send(mac, (uint8_t*)output.c_str(), output.length());
  
  if (result == ESP_OK) {
    Serial.println("Retry request sent successfully");
  } else {
    Serial.println("Error sending retry request");
  }
}

void OnDataRecv(const esp_now_recv_info *recv_info, const uint8_t *incomingData, int len) {
  // FAST PATH - minimal processing in interrupt!
  // Just queue the message for processing in main loop
  
  if (queueCount >= MAX_QUEUE_SIZE) {
    // Queue full - drop packet (shouldn't happen with 20 slots)
    return;
  }
  
  // Add to queue
  memcpy(messageQueue[queueHead].mac, recv_info->src_addr, 6);
  memcpy(messageQueue[queueHead].data, incomingData, min(len, 249));
  messageQueue[queueHead].data[min(len, 249)] = '\0';
  messageQueue[queueHead].len = len;
  messageQueue[queueHead].valid = true;
  
  queueHead = (queueHead + 1) % MAX_QUEUE_SIZE;
  queueCount++;
}

bool isValidJson(String text, int len) {
  text.trim();
  return (text.startsWith("{") && text.endsWith("}") && text.length() >= 2);
}

// Process queued messages in main loop (not interrupt!)
void processQueuedMessages() {
  while (queueCount > 0) {
    // Get message from queue
    QueuedMessage* msg = &messageQueue[queueTail];
    queueTail = (queueTail + 1) % MAX_QUEUE_SIZE;
    queueCount--;
    
    if (!msg->valid) continue;
    
    String payload = String(msg->data);
    payload.trim();
    
    // Check for pairing broadcast: "mother:X"
    if (payload.startsWith("mother:")) {
      int deviceId = payload.substring(7).toInt();
      
      if (deviceId > 0) {
        handlePairingRequest(deviceId, msg->mac);
        continue;
      }
    }
    
    // Check for OTA status messages from children
    if (isValidJson(payload, msg->len)) {
      StaticJsonDocument<256> doc;
      if (deserializeJson(doc, payload) == DeserializationError::Ok) {
        if (doc.containsKey("OTA")) {
          // This is an OTA status message - forward to Python immediately
          Serial.println(payload);
          
          // Update OTA tracking
          if (doc.containsKey("Did")) {
            int deviceId = doc["Did"];
            const char* status = doc["OTA"];
            
            if (strcmp(status, "OTA_READY") == 0) {
              setOTAMode(deviceId, true);
            } else if (strcmp(status, "OTA_SUCCESS") == 0 || 
                       strcmp(status, "OTA_ABORT") == 0 ||
                       strcmp(status, "OTA_REJECT") == 0) {
              setOTAMode(deviceId, false);
            }
          }
          continue;
        }
        
        // Check for CONFIG response messages from children
        if (doc.containsKey("CONFIG")) {
          // This is a config response - forward to Python immediately
          Serial.println(payload);
          continue;
        }
      }
    }
    
    // Validate JSON for normal messages
    if(!isValidJson(payload, msg->len)) {
      sendRetryToChild(msg->mac);
      continue;
    }
      
    // Forward raw JSON to Python script
    Serial.println(payload);

    // Parse JSON to extract DeviceId and optional TerminalId
    StaticJsonDocument<256> doc;
    if (deserializeJson(doc, payload) == DeserializationError::Ok) {
      
      // Handle DeviceId (always present)
      if (doc.containsKey("Did")) {
        int deviceId = doc["Did"].as<int>();
        int terminalId = doc.containsKey("Id") ? doc["Id"].as<int>() : -1;
        
        addOrUpdateTerminalByDeviceId(deviceId, msg->mac, terminalId);
      }
      // Legacy support: Handle old "Id" field (TerminalId)
      else if (doc.containsKey("Id")) {
        int terminalId = doc["Id"];
        addOrUpdateTerminalById(terminalId, msg->mac);
      }
      
      // Print current map for debugging
      if (doc.containsKey("Debug") && doc["Debug"]) {
        printTerminalMap();
      }
    }
  }
}

// ==================== SETUP ====================
void setup() {
  #if defined(ESP32)
    // Set big buffers (these functions available in ESP32 core)
    Serial.setTxBufferSize(4096);
    Serial.setRxBufferSize(4096);
  #endif
  
  Serial.begin(2000000);
  delay(1000);
  
  WiFi.mode(WIFI_STA);
  delay(100); 
  
  Serial.println("\n╔════════════════════════════════════════════════╗");
  Serial.println("║   ESP-NOW Mother Receiver v5.0 (WiFi OTA)    ║");
  Serial.println("║   (OTA Relay + Queue-Based)                   ║");
  Serial.println("╚════════════════════════════════════════════════╝");
  Serial.print("🆔 Mother ID: ");
  Serial.println(MOTHER_ID);
  Serial.print("📡 Mother MAC Address: ");
  Serial.println(WiFi.macAddress());

  if (esp_now_init() != ESP_OK) {
    Serial.println("❌ Error initializing ESP-NOW");
    return;
  }
  
  esp_now_register_recv_cb(OnDataRecv);
  Serial.println("✅ ESP-NOW initialized successfully");
  Serial.println("\n💡 PAIRING MODE:");
  Serial.println("   • When child broadcasts 'mother:X'");
  Serial.println("   • You will be prompted: Y/N to accept");
  Serial.println("   • Type 'Y' to become the new mother");
  Serial.println("   • Child will save your MAC automatically");
  Serial.println("\n🔄 OTA UPDATE MODE:");
  Serial.println("   • WiFi OTA: Children download firmware directly");
  Serial.println("   • Python sends OTA commands via serial");
  Serial.println("   • Mother relays commands to children");
  Serial.println("   • Fast, reliable, battery-efficient");
  Serial.println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  Serial.println("🔘 Listening for messages...\n");
}

// ==================== MAIN LOOP ====================
// Buffer for non-blocking serial reading
String serialBuffer = "";

void loop() {
  // Check for pairing timeout
  checkPairingTimeout();
  
  // Check for OTA timeouts
  checkOTATimeouts();
  
  // Process queued ESP-NOW messages (PRIORITY!)
  processQueuedMessages();
  
  // NON-BLOCKING serial read - read one character at a time
  while (Serial.available() > 0) {
    char c = Serial.read();
    
    if (c == '\n') {
      // Complete line received, process it
      serialBuffer.trim();
      
      if (serialBuffer.length() > 0) {
        processSerialCommand(serialBuffer);
      }
      
      // Clear buffer for next line
      serialBuffer = "";
    } else if (c != '\r') {
      // Add character to buffer (ignore carriage return)
      serialBuffer += c;
    }
  }
  
  // Small delay to prevent CPU hogging while still being responsive
  delay(1);
}

// ==================== PROCESS SERIAL COMMAND ====================
void processSerialCommand(String line) {
  // Check if this is a pairing response (Y/N)
  if (pendingPairing.active) {
    if (line.equalsIgnoreCase("Y") || line.equalsIgnoreCase("YES")) {
      Serial.println("✅ You accepted the pairing request!");
      sendBabyResponse(pendingPairing.mac);
      pendingPairing.active = false;
      return;
    } else {
      Serial.println("❌ You rejected the pairing request");
      pendingPairing.active = false;
      return;
    }
  }
  
  // Otherwise, treat as JSON command from Python
  StaticJsonDocument<512> doc;
  DeserializationError error = deserializeJson(doc, line);
  
  if (error) {
    Serial.print("JSON Parse Error: ");
    Serial.println(error.c_str());
    return;
  }
  
  // ==================== OTA COMMAND HANDLING ====================
  // Handle OTA commands specially
  if (doc.containsKey("OTA_CMD")) {
    handleOTACommand(doc);
    return;
  }
  
  // Handle OTA binary data (special marker)
  if (doc.containsKey("OTA_DATA")) {
    handleOTABinaryData(doc);
    return;
  }
  
  // ==================== CONFIG COMMAND HANDLING ====================
  // Handle configuration commands
  if (doc.containsKey("CONFIG_CMD")) {
    handleConfigCommand(doc);
    return;
  }
  
  // Handle different types of messages from Python
  
  // 1. Response to specific terminal (by TerminalId or DeviceId)
  if (doc.containsKey("Id") && doc.containsKey("c")) {
    int terminalId = doc["Id"];
    int deviceId = doc["Did"];
    
    uint8_t* targetMac = nullptr;
    
    if (terminalId > 0) {
      targetMac = findMacByTerminalId(terminalId);
      if(targetMac) sendToDevice(targetMac, line, "Terminal", String(terminalId));
    } else if(deviceId > 0) {
      targetMac = findMacByDeviceId(deviceId);
      if(targetMac) sendToDevice(targetMac, line, "Device", String(deviceId));  
    }
    
    if(!targetMac) {
      Serial.print("No MAC found for TerminalId: ");
      Serial.println(terminalId);
    }
    
    if(deviceId > 0 && terminalId > 0) updateDeviceTerminalId(deviceId, terminalId);
  }
  // 2. Terminal ID assignment update
  else if (doc.containsKey("UpdateTerminal")) {
    int deviceId = doc["DeviceId"];
    int newTerminalId = doc["NewTerminalId"];
    updateDeviceTerminalId(deviceId, newTerminalId);
  }
  // 3. Debug command
  else if (doc.containsKey("Debug")) {
    printTerminalMap();
  }
  else {
    Serial.println("Unknown command format");
  }
}

// ==================== OTA COMMAND HANDLERS ====================
void handleOTACommand(JsonDocument& doc) {
  const char* cmd = doc["OTA_CMD"];
  int deviceId = doc["Did"] | 0;
  
  if (deviceId == 0) {
    Serial.println("❌ OTA command missing Device ID");
    return;
  }
  
  uint8_t* targetMac = findMacByDeviceId(deviceId);
  if (!targetMac) {
    Serial.print("❌ No MAC found for Device ID: ");
    Serial.println(deviceId);
    return;
  }
  
  Serial.print("🔄 Relaying OTA command '");
  Serial.print(cmd);
  Serial.print("' to Device ");
  Serial.println(deviceId);
  
  // Handle WiFi OTA (new method)
  if (strcmp(cmd, "WIFI_UPDATE") == 0) {
    const char* firmwareURL = doc["URL"];
    if (firmwareURL && strlen(firmwareURL) > 0) {
      Serial.print("📡 WiFi OTA URL: ");
      Serial.println(firmwareURL);
      
      // Forward WiFi OTA command to child
      String output;
      serializeJson(doc, output);
      sendToDevice(targetMac, output, "Device", String(deviceId));
      
      // Track OTA mode
      setOTAMode(deviceId, true);
    } else {
      Serial.println("❌ Missing firmware URL");
    }
    return;
  }
  
  // Forward OTA command to child (legacy ESP-NOW OTA)
  String output;
  serializeJson(doc, output);
  sendToDevice(targetMac, output, "Device", String(deviceId));
  
  // Track OTA mode for START command
  if (strcmp(cmd, "START") == 0) {
    setOTAMode(deviceId, true);
  } else if (strcmp(cmd, "END") == 0 || strcmp(cmd, "ABORT") == 0) {
    setOTAMode(deviceId, false);
  }
}

void handleOTABinaryData(JsonDocument& doc) {
  int deviceId = doc["Did"] | 0;
  
  if (deviceId == 0) {
    Serial.println("❌ OTA data missing Device ID");
    return;
  }
  
  uint8_t* targetMac = findMacByDeviceId(deviceId);
  if (!targetMac) {
    Serial.print("❌ No MAC found for Device ID: ");
    Serial.println(deviceId);
    return;
  }
  
  // Extract base64 or hex encoded data
  const char* dataStr = doc["OTA_DATA"];
  if (!dataStr) {
    Serial.println("❌ OTA_DATA field missing");
    return;
  }
  
  // For now, we'll use hex encoding for simplicity
  // Format: "AABBCCDD..." where each byte is 2 hex chars
  int dataLen = strlen(dataStr) / 2;
  uint8_t binaryData[250];  // ESP-NOW max is ~250 bytes
  
  if (dataLen > 250) {
    Serial.println("❌ OTA data chunk too large");
    return;
  }
  
  // Convert hex string to binary
  for (int i = 0; i < dataLen; i++) {
    char byteStr[3] = {dataStr[i*2], dataStr[i*2+1], 0};
    binaryData[i] = (uint8_t)strtol(byteStr, NULL, 16);
  }
  
  // Send binary data via ESP-NOW
  esp_err_t result = esp_now_send(targetMac, binaryData, dataLen);
  
  if (result == ESP_OK) {
    // Don't spam - only log errors
  } else {
    Serial.print("❌ OTA data send failed: ");
    Serial.println(result);
  }
}

void handleConfigCommand(JsonDocument& doc) {
  const char* cmd = doc["CONFIG_CMD"];
  int deviceId = doc["Did"] | 0;
  
  if (deviceId == 0) {
    Serial.println("❌ Config command missing Device ID");
    return;
  }
  
  uint8_t* targetMac = findMacByDeviceId(deviceId);
  if (!targetMac) {
    Serial.print("❌ No MAC found for Device ID: ");
    Serial.println(deviceId);
    return;
  }
  
  Serial.print("🔧 Relaying config command '");
  Serial.print(cmd);
  Serial.print("' to Device ");
  Serial.println(deviceId);
  
  // Forward config command to child
  String output;
  serializeJson(doc, output);
  sendToDevice(targetMac, output, "Device", String(deviceId));
}

// ==================== HELPER FUNCTIONS ====================
void sendToDevice(uint8_t* targetMac, const String& message, const String& idType, const String& idValue) {
  // Add peer if not known
  if (!esp_now_is_peer_exist(targetMac)) {
    esp_now_peer_info_t peerInfo = {};
    memcpy(peerInfo.peer_addr, targetMac, 6);
    peerInfo.channel = 0;
    peerInfo.encrypt = false;
    esp_err_t result = esp_now_add_peer(&peerInfo);
    if (result != ESP_OK) {
      Serial.print("Failed to add peer: ");
      Serial.println(result);
      return;
    }
  }

  esp_err_t result = esp_now_send(targetMac, (uint8_t*)message.c_str(), message.length());
  // Uncomment for debugging:
  // if (result == ESP_OK) {
  //   Serial.print("✅ Sent to ");
  //   Serial.print(idType);
  //   Serial.print(" ");
  //   Serial.println(idValue);
  // }
}

void updateDeviceTerminalId(int deviceId, int newTerminalId) {
  for (int i = 0; i < terminalCount; i++) {
    if (terminals[i].deviceId == deviceId) {
      terminals[i].terminalId = newTerminalId;
      return;
    }
  }
  Serial.print("❌ Device not found for Terminal ID update: ");
  Serial.println(deviceId);
}
