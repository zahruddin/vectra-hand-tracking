#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>

// =====================================================
// VECTRA / CYBERHAND ESP32 FIRMWARE
// Mode komunikasi:
// ESP32 -> Python Server menggunakan PLAIN WEBSOCKET
// Endpoint: ws://host:port/esp32 atau wss://domain:443/esp32
//
// Tambahan:
// - Cek koneksi modul PCA9685 melalui I2C address 0x40
// - Status PCA tampil di Serial Monitor dan halaman config ESP32
// =====================================================

// Pin I2C default ESP32
#define I2C_SDA 21
#define I2C_SCL 22

// Address default PCA9685
#define PCA9685_ADDR 0x40

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(PCA9685_ADDR);

// PCA9685 channel mapping:
// 0 = Jempol, 1 = Telunjuk, 2 = Tengah, 3 = Manis, 4 = Kelingking
const int servoPins[5] = {0, 1, 2, 3, 4};

// Web server konfigurasi lokal ESP32
WebServer server(80);
Preferences pref;

// Plain WebSocket client
WebSocketsClient webSocket;
bool websocketConnected = false;

// Status PCA9685
bool pcaDetected = false;
bool pcaInitialized = false;
unsigned long lastPcaCheck = 0;

// Konfigurasi tersimpan di flash
String wifi_ssid = "";
String wifi_pass = "";

// Untuk Cloudflare Tunnel:
// host  = domain saja, tanpa https:// dan tanpa /
// port  = 443
// ssl   = true
String server_host = "192.168.18.13";
int server_port = 5000;
bool use_ssl = false;

// Servo smoothing
float currentPulses[5] = {130.0, 135.0, 130.0, 135.0, 130.0};
float targetPulses[5]  = {130.0, 135.0, 130.0, 135.0, 130.0};

// Reverse servo per jari. Nilai ini dikirim dari dashboard Python.
// Reverse dipakai untuk penempatan servo yang arahnya berkebalikan.
bool servoReverse[5] = {false, false, false, false, false};
int servoCalMin[5] = {130, 130, 130, 130, 130};
int servoCalMax[5] = {490, 490, 490, 490, 490};

const float SMOOTH_FACTOR = 0.15;

unsigned long lastWebSocketReconnectAttempt = 0;
unsigned long lastStatusPrint = 0;
unsigned long lastEsp32Ping = 0;
unsigned long lastServoUpdate = 0;

// =====================================================
// CEK PCA9685 / I2C
// =====================================================
bool checkI2CDevice(uint8_t address) {
  Wire.beginTransmission(address);
  byte error = Wire.endTransmission();
  return (error == 0);
}

void scanI2CBus() {
  Serial.println("🔎 Scan I2C bus...");
  bool foundAny = false;

  for (uint8_t address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    byte error = Wire.endTransmission();

    if (error == 0) {
      foundAny = true;
      Serial.print("✅ I2C device ditemukan di address 0x");
      if (address < 16) Serial.print("0");
      Serial.println(address, HEX);
    }
  }

  if (!foundAny) {
    Serial.println("❌ Tidak ada device I2C terdeteksi. Cek SDA, SCL, VCC, dan GND.");
  }
}

void initPCA9685() {
  if (!pcaDetected) return;

  Serial.println("⚙️ Inisialisasi PCA9685...");
  pwm.begin();
  pwm.setOscillatorFrequency(27000000);
  pwm.setPWMFreq(50);
  delay(20);

  for (int i = 0; i < 5; i++) {
    pwm.setPWM(servoPins[i], 0, (int)currentPulses[i]);
  }

  pcaInitialized = true;
  Serial.println("✅ PCA9685 siap. Servo channel 0-4 sudah diberi posisi awal.");
}

void checkPCA9685Status(bool printAlways = false) {
  bool nowDetected = checkI2CDevice(PCA9685_ADDR);

  if (nowDetected && !pcaDetected) {
    pcaDetected = true;
    Serial.println("✅ PCA9685 TERDETEKSI di I2C address 0x40");
    initPCA9685();
  } else if (!nowDetected && pcaDetected) {
    pcaDetected = false;
    pcaInitialized = false;
    Serial.println("❌ PCA9685 TERPUTUS dari I2C address 0x40");
  } else if (printAlways) {
    if (nowDetected) {
      Serial.println("✅ PCA9685 OK di address 0x40");
    } else {
      Serial.println("❌ PCA9685 TIDAK TERDETEKSI di address 0x40");
      Serial.println("   Cek: VCC=3V3, GND common, SDA=GPIO21, SCL=GPIO22.");
    }
  }
}

// =====================================================
// UTILITAS
// =====================================================
String cleanHost(String host) {
  host.trim();
  host.replace("https://", "");
  host.replace("http://", "");
  host.replace("wss://", "");
  host.replace("ws://", "");

  int slashIndex = host.indexOf('/');
  if (slashIndex >= 0) {
    host = host.substring(0, slashIndex);
  }

  int colonIndex = host.indexOf(':');
  if (colonIndex >= 0) {
    host = host.substring(0, colonIndex);
  }

  host.trim();
  return host;
}

void applyPulseTargets(float pulses[5]) {
  String csv = "";
  String logAngles = "📐 Sudut: ";

  for (int i = 0; i < 5; i++) {
    float pulseVal = constrain(pulses[i], 100.0, 600.0);
    targetPulses[i] = pulseVal;

    if (i > 0) csv += ",";
    csv += String((int)round(pulseVal));

    float default_min = 130.0;
    float default_max = 490.0;
    float angle = ((pulseVal - default_min) * 180.0) / (default_max - default_min);
    int finalAngle = constrain(round(angle), 0, 180);

    logAngles += String(finalAngle);
    if (i < 4) logAngles += "°, ";
    else logAngles += "°";
  }

  Serial.print("📥 PWM WebSocket: ");
  Serial.print(csv);
  Serial.print("  |  ");
  Serial.println(logAngles);

  if (!pcaDetected || !pcaInitialized) {
    Serial.println("⚠️ Data PWM diterima, tetapi PCA9685 belum terdeteksi. Servo tidak bisa digerakkan.");
  }
}

void parsePulsesJson(JsonArray arr) {
  if (arr.size() < 5) return;

  float pulses[5];
  for (int i = 0; i < 5; i++) {
    pulses[i] = arr[i].as<float>();
  }

  applyPulseTargets(pulses);
}

void parseServoConfig(JsonDocument &doc) {
  bool changed = false;

  if (doc["reverse"].is<JsonArray>()) {
    JsonArray rev = doc["reverse"].as<JsonArray>();
    for (int i = 0; i < 5 && i < rev.size(); i++) {
      servoReverse[i] = rev[i].as<bool>();
    }
    changed = true;
  }

  if (doc["min"].is<JsonArray>()) {
    JsonArray mn = doc["min"].as<JsonArray>();
    for (int i = 0; i < 5 && i < mn.size(); i++) {
      servoCalMin[i] = mn[i].as<int>();
    }
    changed = true;
  }

  if (doc["max"].is<JsonArray>()) {
    JsonArray mx = doc["max"].as<JsonArray>();
    for (int i = 0; i < 5 && i < mx.size(); i++) {
      servoCalMax[i] = mx[i].as<int>();
    }
    changed = true;
  }

  if (changed) {
    Serial.print("🔁 Reverse config: ");
    for (int i = 0; i < 5; i++) {
      Serial.print(servoReverse[i] ? "ON" : "OFF");
      if (i < 4) Serial.print(", ");
    }
    Serial.println();
  }
}

void applyAnglesFromServer(JsonArray angles) {
  if (angles.size() < 5) return;

  float pulses[5];
  for (int i = 0; i < 5; i++) {
    float angle = constrain(angles[i].as<float>(), 0.0, 180.0);
    if (servoReverse[i]) {
      angle = 180.0 - angle;
    }

    int cMin = servoCalMin[i];
    int cMax = servoCalMax[i];
    pulses[i] = cMin + (angle * (cMax - cMin) / 180.0);
  }

  applyPulseTargets(pulses);
}

void parseSerialPulses(String data) {
  float pulses[5] = {130, 135, 130, 135, 130};
  int idx = 0;
  int startPos = 0;

  for (int i = 0; i <= data.length(); i++) {
    if (data.charAt(i) == ',' || i == data.length()) {
      if (idx < 5) {
        String part = data.substring(startPos, i);
        pulses[idx] = part.toFloat();
      }
      startPos = i + 1;
      idx++;
    }
  }

  if (idx >= 5) {
    applyPulseTargets(pulses);
  }
}

// =====================================================
// WEBSOCKET EVENT HANDLER
// =====================================================
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      websocketConnected = false;
      Serial.println("⚠️ WebSocket ESP32 terputus dari server Python");
      break;

    case WStype_CONNECTED:
      websocketConnected = true;
      Serial.println("✅ WebSocket ESP32 terhubung ke server Python");

      webSocket.sendTXT("{\"type\":\"register_esp32\",\"device\":\"CyberHand ESP32\",\"firmware\":\"plain_ws_pca_reverse\"}");
      Serial.println("🤖 Mengirim register_esp32 ke server...");
      break;

    case WStype_TEXT: {
      String msg = String((char*)payload).substring(0, length);
      Serial.print("📨 Data WebSocket masuk: ");
      Serial.println(msg);

      DynamicJsonDocument doc(1024);
      DeserializationError error = deserializeJson(doc, msg);

      if (error) {
        Serial.print("❌ JSON error: ");
        Serial.println(error.c_str());
        return;
      }

      String msgType = doc["type"] | "";

      // Dashboard Python dapat mengirim konfigurasi reverse/min/max bersama data.
      // Untuk payload type=pulses, pulse sudah final dari server/browser, jadi ESP32 TIDAK membalik lagi agar tidak double reverse.
      // Reverse akan dipakai jika server mengirim type=angles.
      parseServoConfig(doc);

      if (msgType == "pulses") {
        JsonArray arr = doc["pulses"].as<JsonArray>();
        if (arr.size() >= 5) {
          parsePulsesJson(arr);
        }
      } else if (msgType == "angles") {
        JsonArray angles = doc["angles"].as<JsonArray>();
        if (angles.size() >= 5) {
          applyAnglesFromServer(angles);
        }
      } else if (msgType == "servo_config") {
        Serial.println("✅ Konfigurasi servo/reverse diterima dari server");
      } else if (msgType == "registered") {
        Serial.println("✅ Server menerima register ESP32");
      } else if (msgType == "pong") {
        Serial.println("💓 Pong dari server");
      } else if (msgType == "csv") {
        String csv = doc["data"] | "";
        parseSerialPulses(csv);
      }

      break;
    }

    case WStype_ERROR:
      websocketConnected = false;
      Serial.println("❌ WebSocket error");
      break;

    default:
      break;
  }
}

void connectWebSocket() {
  if (WiFi.status() != WL_CONNECTED) return;

  String host = cleanHost(server_host);
  if (host.length() == 0) {
    Serial.println("⚠️ Host server kosong.");
    return;
  }

  Serial.print("🔌 Menghubungkan WebSocket ke ");
  Serial.print(use_ssl ? "wss://" : "ws://");
  Serial.print(host);
  Serial.print(":");
  Serial.print(server_port);
  Serial.println("/esp32");

  webSocket.disconnect();

  if (use_ssl) {
    webSocket.beginSSL(host.c_str(), server_port, "/esp32");
  } else {
    webSocket.begin(host.c_str(), server_port, "/esp32");
  }

  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
}

// =====================================================
// HALAMAN KONFIGURASI ESP32
// =====================================================
void handleRoot() {
  String html = "";
  html += "<!DOCTYPE html><html><head><meta charset='UTF-8'>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1.0'>";
  html += "<title>CyberHand Config</title>";
  html += "<script src='https://cdn.tailwindcss.com'></script>";
  html += "</head>";
  html += "<body class='bg-gray-950 text-gray-100 font-sans min-h-screen flex items-center justify-center p-4'>";
  html += "<div class='max-w-md w-full bg-gray-900 border border-gray-800 p-6 rounded-2xl shadow-2xl'>";
  html += "<h1 class='text-2xl font-black text-center bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-indigo-400 mb-2'>🦾 CYBERHAND CONFIG</h1>";
  html += "<p class='text-xs text-gray-400 text-center mb-6'>ESP32 plain WebSocket mode: /esp32</p>";

  html += "<div class='bg-gray-950 p-3 rounded-xl border border-gray-800 text-xs space-y-1 mb-6'>";

  html += "<div>📶 <span class='text-gray-400'>Status Wi-Fi:</span> <span class='font-bold ";
  html += WiFi.status() == WL_CONNECTED ? "text-green-400" : "text-red-400";
  html += "'>";
  html += WiFi.status() == WL_CONNECTED ? "TERHUBUNG" : "TERPUTUS";
  html += "</span></div>";

  html += "<div>🏠 <span class='text-gray-400'>Wi-Fi Terhubung:</span> <span class='font-mono'>";
  html += WiFi.SSID();
  html += "</span></div>";

  html += "<div>📍 <span class='text-gray-400'>IP Lokal STA:</span> <span class='font-mono text-blue-400'>";
  html += WiFi.localIP().toString();
  html += "</span></div>";

  html += "<div>🧩 <span class='text-gray-400'>PCA9685:</span> <span class='font-mono ";
  html += pcaDetected ? "text-green-400" : "text-red-400";
  html += "'>";
  html += pcaDetected ? "TERDETEKSI 0x40" : "TIDAK TERDETEKSI";
  html += "</span></div>";

  html += "<div>🖥️ <span class='text-gray-400'>Target Server:</span> <span class='font-mono text-yellow-400'>";
  html += cleanHost(server_host) + ":" + String(server_port) + "/esp32";
  html += "</span></div>";

  html += "<div>🔐 <span class='text-gray-400'>SSL/WSS:</span> <span class='font-mono ";
  html += use_ssl ? "text-green-400" : "text-yellow-400";
  html += "'>";
  html += use_ssl ? "AKTIF" : "NONAKTIF";
  html += "</span></div>";

  html += "<div>🔗 <span class='text-gray-400'>WebSocket:</span> <span class='font-mono ";
  html += websocketConnected ? "text-green-400" : "text-red-400";
  html += "'>";
  html += websocketConnected ? "TERHUBUNG" : "BELUM TERHUBUNG";
  html += "</span></div>";

  html += "</div>";

  html += "<form action='/save' method='POST' class='space-y-4'>";
  html += "<div><label class='block text-xs font-bold text-gray-400 uppercase mb-1'>SSID Wi-Fi Rumah</label>";
  html += "<input type='text' name='ssid' value='" + wifi_ssid + "' class='w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white'></div>";

  html += "<div><label class='block text-xs font-bold text-gray-400 uppercase mb-1'>Password Wi-Fi</label>";
  html += "<input type='password' name='pass' value='" + wifi_pass + "' class='w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white'></div>";

  html += "<div><label class='block text-xs font-bold text-gray-400 uppercase mb-1'>Domain / IP Server Python</label>";
  html += "<input type='text' name='host' value='" + server_host + "' placeholder='vectra.seefan.my.id' class='w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white'></div>";

  html += "<div><label class='block text-xs font-bold text-gray-400 uppercase mb-1'>Port Server</label>";
  html += "<input type='number' name='port' value='" + String(server_port) + "' class='w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white'></div>";

  html += "<label class='flex items-center gap-2 text-xs text-gray-300'>";
  html += "<input type='checkbox' name='ssl' value='1' ";
  html += use_ssl ? "checked" : "";
  html += "> Pakai SSL/WSS untuk Cloudflare Tunnel</label>";

  html += "<p class='text-[11px] text-gray-500 leading-relaxed'>";
  html += "Untuk Cloudflare Tunnel: isi domain saja tanpa https://, port 443, dan centang SSL/WSS.<br>";
  html += "PCA9685 wiring: SDA=GPIO21, SCL=GPIO22, VCC=3V3, GND common.";
  html += "</p>";

  html += "<button type='submit' class='w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-2.5 rounded-lg shadow-lg transition duration-150 mt-2'>Simpan & Terapkan</button>";
  html += "</form></div></body></html>";

  server.send(200, "text/html", html);
}

void handleSave() {
  if (server.method() != HTTP_POST) {
    server.send(405, "text/plain", "Method Not Allowed");
    return;
  }

  wifi_ssid = server.arg("ssid");
  wifi_pass = server.arg("pass");
  server_host = cleanHost(server.arg("host"));
  server_port = server.arg("port").toInt();
  use_ssl = server.hasArg("ssl");

  if (server_port <= 0) {
    server_port = use_ssl ? 443 : 5000;
  }

  pref.begin("cyberhand", false);
  pref.putString("ssid", wifi_ssid);
  pref.putString("pass", wifi_pass);
  pref.putString("host", server_host);
  pref.putInt("port", server_port);
  pref.putBool("ssl", use_ssl);
  pref.end();

  String html = "<html><body style='background:#0f172a;color:#f8fafc;font-family:sans-serif;text-align:center;padding-top:50px;'>";
  html += "<h2>✅ Konfigurasi Berhasil Disimpan!</h2>";
  html += "<p>ESP32 sedang mencoba menghubungkan ulang Wi-Fi dan WebSocket...</p>";
  html += "<script>setTimeout(function(){window.location.href='/';}, 3000);</script>";
  html += "</body></html>";
  server.send(200, "text/html", html);

  delay(1000);

  webSocket.disconnect();
  websocketConnected = false;

  WiFi.disconnect();
  Serial.println("\n🔄 Mencoba terhubung ke Wi-Fi baru: " + wifi_ssid);
  WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());

  lastWebSocketReconnectAttempt = 0;
}

// =====================================================
// SETUP
// =====================================================
void setup() {
  Serial.begin(115200);
  Serial.println("\n=== BOOTING CYBERHAND ESP32 PLAIN WEBSOCKET ===");

  Wire.begin(I2C_SDA, I2C_SCL);
  Serial.print("🔧 I2C aktif. SDA=GPIO");
  Serial.print(I2C_SDA);
  Serial.print(", SCL=GPIO");
  Serial.println(I2C_SCL);

  scanI2CBus();
  checkPCA9685Status(true);

  pref.begin("cyberhand", true);
  wifi_ssid = pref.getString("ssid", "");
  wifi_pass = pref.getString("pass", "");
  server_host = pref.getString("host", "");

  if (server_host == "") {
    server_host = pref.getString("ip", "192.168.18.13");
  }

  server_port = pref.getInt("port", 5000);
  use_ssl = pref.getBool("ssl", false);
  pref.end();

  server_host = cleanHost(server_host);

  WiFi.mode(WIFI_AP_STA);

  WiFi.softAP("CyberHand-Robot", "password123");
  Serial.print("📡 Hotspot Mandiri Aktif! Akses config di: ");
  Serial.println(WiFi.softAPIP());

  if (wifi_ssid != "") {
    WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());
    Serial.println("🔄 Mencoba tersambung ke Wi-Fi: " + wifi_ssid);
  } else {
    Serial.println("⚠️ Belum ada data Wi-Fi tersimpan. Hubungkan ke Hotspot ESP32 untuk konfigurasi.");
  }

  server.on("/", handleRoot);
  server.on("/save", handleSave);
  server.begin();

  Serial.println("🌐 Web Server Internal Siaga di Port 80");
}

// =====================================================
// LOOP
// =====================================================
void loop() {
  server.handleClient();

  if (millis() - lastPcaCheck > 5000) {
    lastPcaCheck = millis();
    checkPCA9685Status(false);
  }

  if (WiFi.status() == WL_CONNECTED) {
    if (!websocketConnected && millis() - lastWebSocketReconnectAttempt > 5000) {
      lastWebSocketReconnectAttempt = millis();
      connectWebSocket();
    }

    webSocket.loop();

    if (websocketConnected && millis() - lastEsp32Ping > 3000) {
      lastEsp32Ping = millis();
      webSocket.sendTXT(String("{\"type\":\"ping\",\"device\":\"CyberHand ESP32\",\"pca\":") + (pcaDetected ? "true" : "false") + "}");
    }
  } else {
    websocketConnected = false;
  }

  if (millis() - lastStatusPrint > 10000) {
    lastStatusPrint = millis();

    Serial.print("📶 Wi-Fi: ");
    Serial.print(WiFi.status() == WL_CONNECTED ? "OK" : "OFF");

    Serial.print(" | PCA9685: ");
    Serial.print(pcaDetected ? "OK" : "OFF");

    Serial.print(" | WebSocket: ");
    Serial.print(websocketConnected ? "OK" : "OFF");

    Serial.print(" | Target: ");
    Serial.print(use_ssl ? "wss://" : "ws://");
    Serial.print(cleanHost(server_host));
    Serial.print(":");
    Serial.print(server_port);
    Serial.println("/esp32");
  }

  if (pcaDetected && pcaInitialized && millis() - lastServoUpdate >= 10) {
    lastServoUpdate = millis();

    for (int i = 0; i < 5; i++) {
      float diff = targetPulses[i] - currentPulses[i];

      if (abs(diff) > 0.1) {
        currentPulses[i] += diff * SMOOTH_FACTOR;
        pwm.setPWM(servoPins[i], 0, round(currentPulses[i]));
      }
    }
  }
}
