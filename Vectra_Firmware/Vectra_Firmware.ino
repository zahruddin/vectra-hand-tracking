#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <SocketIOclient.h>
#include <ArduinoJson.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

// Port PCA9685: 0=Jempol, 1=Telunjuk, 2=Tengah, 3=Manis, 4=Kelingking
const int servoPins[5] = {0, 1, 2, 3, 4};

// Web server konfigurasi lokal ESP32
WebServer server(80);
Preferences pref;

// Socket.IO client ke Python server / Cloudflare Tunnel
SocketIOclient socketIO;
bool socketConnected = false;

// Variabel konfigurasi dinamis dari Flash Memory
String wifi_ssid = "";
String wifi_pass = "";

// Untuk Cloudflare Tunnel gunakan domain tanpa https:// dan tanpa slash belakang.
// Contoh: vectra-sdmuhla.trycloudflare.com
String server_host = "192.168.18.13";
int server_port = 5000;
bool use_ssl = false;   // true untuk Cloudflare Tunnel / HTTPS / WSS, false untuk lokal HTTP

// Variabel pergerakan servo
float currentPulses[5] = {130.0, 135.0, 130.0, 135.0, 130.0};
float targetPulses[5]  = {130.0, 135.0, 130.0, 135.0, 130.0};
const float SMOOTH_FACTOR = 0.15;

unsigned long lastSocketReconnectAttempt = 0;
unsigned long lastStatusPrint = 0;

// ==========================================
// UTILITAS
// ==========================================
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
    float pulseVal = constrain(pulses[i], 100.0, 550.0);
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
}

void parsePulsesJson(JsonArray arr) {
  if (arr.size() < 5) return;

  float pulses[5];
  for (int i = 0; i < 5; i++) {
    pulses[i] = arr[i].as<float>();
  }
  applyPulseTargets(pulses);
}

// Fallback jika suatu saat server mengirim CSV, misalnya "130,480,130,480,130"
void parseSerialPulses(String data) {
  float pulses[5];
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

// ==========================================
// SOCKET.IO EVENT HANDLER
// ==========================================
void socketIOEvent(socketIOmessageType_t type, uint8_t * payload, size_t length) {
  switch (type) {
    case sIOtype_DISCONNECT:
      socketConnected = false;
      Serial.println("⚠️ Socket.IO terputus dari server Python");
      break;

    case sIOtype_CONNECT:
      socketConnected = true;
      Serial.println("✅ Socket.IO transport terhubung ke server Python");

      // WAJIB untuk masuk ke namespace default Flask-SocketIO "/"
      socketIO.send(sIOtype_CONNECT, "/");
      delay(100);

      // Daftarkan diri sebagai ESP32 ke server Python
      socketIO.sendEVENT("[\"register_esp32\",{\"device\":\"CyberHand ESP32\"}]");
      Serial.println("🤖 Mengirim register_esp32 ke server...");
      break;

    case sIOtype_EVENT: {
      String msg = String((char*)payload).substring(0, length);
      Serial.print("📨 Event masuk: ");
      Serial.println(msg);

      DynamicJsonDocument doc(1024);
      DeserializationError error = deserializeJson(doc, msg);
      if (error) {
        Serial.print("❌ JSON error: ");
        Serial.println(error.c_str());
        return;
      }

      // Format Socket.IO event dari Python:
      // ["pulses", {"pulses": [130, 135, 130, 135, 130]}]
      const char* eventName = doc[0];

      if (eventName && String(eventName) == "pulses") {
        JsonVariant data = doc[1];

        if (data.is<JsonObject>() && data["pulses"].is<JsonArray>()) {
          parsePulsesJson(data["pulses"].as<JsonArray>());
        } else if (data.is<JsonArray>()) {
          parsePulsesJson(data.as<JsonArray>());
        } else if (data.is<const char*>()) {
          parseSerialPulses(String(data.as<const char*>()));
        }
      }
      break;
    }

    case sIOtype_ACK:
      Serial.println("ℹ️ Socket.IO ACK diterima");
      break;

    case sIOtype_ERROR:
      Serial.print("❌ Socket.IO error: ");
      Serial.write(payload, length);
      Serial.println();
      break;

    default:
      break;
  }
}

void connectSocketIO() {
  if (WiFi.status() != WL_CONNECTED) return;

  String host = cleanHost(server_host);
  if (host.length() == 0) return;

  Serial.print("🔌 Menghubungkan Socket.IO ke ");
  Serial.print(use_ssl ? "wss://" : "ws://");
  Serial.print(host);
  Serial.print(":");
  Serial.println(server_port);

  socketIO.disconnect();

  // Flask-SocketIO server memakai path default /socket.io/?EIO=4
  if (use_ssl) {
    socketIO.beginSSL(host.c_str(), server_port, "/socket.io/?EIO=4");
  } else {
    socketIO.begin(host.c_str(), server_port, "/socket.io/?EIO=4");
  }

  socketIO.onEvent(socketIOEvent);
  socketIO.setReconnectInterval(5000);
}

// ==========================================
// HALAMAN KONFIGURASI ESP32
// ==========================================
void handleRoot() {
  String html = "<!DOCTYPE html><html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'>";
  html += "<title>CyberHand Config</title>";
  html += "<script src='https://cdn.tailwindcss.com'></script></head>";
  html += "<body class='bg-gray-950 text-gray-100 font-sans min-h-screen flex items-center justify-center p-4'>";
  html += "<div class='max-w-md w-full bg-gray-900 border border-gray-800 p-6 rounded-2xl shadow-2xl'>";
  html += "<h1 class='text-2xl font-black text-center bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-indigo-400 mb-2'>🦾 CYBERHAND CONFIG</h1>";
  html += "<p class='text-xs text-gray-400 text-center mb-6'>Mode baru: ESP32 konek ke Python via WebSocket/Socket.IO</p>";

  html += "<div class='bg-gray-950 p-3 rounded-xl border border-gray-800 text-xs space-y-1 mb-6'>";
  html += "<div>🔴 <span class='text-gray-400'>Status Wi-Fi:</span> <span class='font-bold " + String(WiFi.status() == WL_CONNECTED ? "text-green-400" : "text-red-400") + "'>" + String(WiFi.status() == WL_CONNECTED ? "TERHUBUNG" : "TERPUTUS") + "</span></div>";
  html += "<div>🏠 <span class='text-gray-400'>Wi-Fi Terhubung:</span> <span class='font-mono'>" + WiFi.SSID() + "</span></div>";
  html += "<div>📍 <span class='text-gray-400'>IP Lokal STA:</span> <span class='font-mono text-blue-400'>" + WiFi.localIP().toString() + "</span></div>";
  html += "<div>🖥️ <span class='text-gray-400'>Target Server:</span> <span class='font-mono text-yellow-400'>" + cleanHost(server_host) + ":" + String(server_port) + "</span></div>";
  html += "<div>🔐 <span class='text-gray-400'>Mode SSL/WSS:</span> <span class='font-mono " + String(use_ssl ? "text-green-400" : "text-yellow-400") + "'>" + String(use_ssl ? "AKTIF" : "NONAKTIF") + "</span></div>";
  html += "<div>🔗 <span class='text-gray-400'>Socket.IO:</span> <span class='font-mono " + String(socketConnected ? "text-green-400" : "text-red-400") + "'>" + String(socketConnected ? "TERHUBUNG" : "BELUM TERHUBUNG") + "</span></div>";
  html += "</div>";

  html += "<form action='/save' method='POST' class='space-y-4'>";
  html += "<div><label class='block text-xs font-bold text-gray-400 uppercase mb-1'>SSID Wi-Fi Rumah</label><input type='text' name='ssid' value='" + wifi_ssid + "' class='w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500'></div>";
  html += "<div><label class='block text-xs font-bold text-gray-400 uppercase mb-1'>Password Wi-Fi</label><input type='password' name='pass' value='" + wifi_pass + "' class='w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500'></div>";
  html += "<div><label class='block text-xs font-bold text-gray-400 uppercase mb-1'>Domain / IP Server Python</label><input type='text' name='host' value='" + server_host + "' placeholder='contoh.trycloudflare.com' class='w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500'></div>";
  html += "<div><label class='block text-xs font-bold text-gray-400 uppercase mb-1'>Port Server</label><input type='number' name='port' value='" + String(server_port) + "' class='w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500'></div>";
  html += "<label class='flex items-center gap-2 text-xs text-gray-300'><input type='checkbox' name='ssl' value='1' " + String(use_ssl ? "checked" : "") + "> Pakai SSL/WSS untuk Cloudflare Tunnel</label>";
  html += "<p class='text-[11px] text-gray-500 leading-relaxed'>Untuk Cloudflare Tunnel: isi domain saja tanpa https://, port 443, dan centang SSL/WSS.</p>";
  html += "<button type='submit' class='w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-2.5 rounded-lg shadow-lg transition duration-150 mt-2'>Simpan & Terapkan</button>";
  html += "</form></div></body></html>";

  server.send(200, "text/html", html);
}

void handleSave() {
  if (server.method() == HTTP_POST) {
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
    html += "<h2>✅ Konfigurasi Berhasil Disimpan!</h2><p>ESP32 sedang mencoba menghubungkan ulang Wi-Fi dan WebSocket...</p>";
    html += "<script>setTimeout(function(){window.location.href='/';}, 3000);</script></body></html>";
    server.send(200, "text/html", html);

    delay(1000);

    socketIO.disconnect();
    socketConnected = false;

    WiFi.disconnect();
    Serial.println("\n🔄 Mencoba terhubung ke Wi-Fi baru: " + wifi_ssid);
    WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());

    lastSocketReconnectAttempt = 0;
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("\n=== BOOTING CYBERHAND ESP32 SOCKET.IO ===");

  pwm.begin();
  pwm.setOscillatorFrequency(27000000);
  pwm.setPWMFreq(50);
  delay(20);

  for (int i = 0; i < 5; i++) {
    pwm.setPWM(servoPins[i], 0, (int)currentPulses[i]);
  }

  pref.begin("cyberhand", true);
  wifi_ssid = pref.getString("ssid", "");
  wifi_pass = pref.getString("pass", "");

  // Kompatibel dengan konfigurasi lama yang menyimpan key "ip"
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

void loop() {
  server.handleClient();

  if (WiFi.status() == WL_CONNECTED) {
    socketIO.loop();

    static unsigned long lastEsp32Ping = 0;

    if (socketConnected && millis() - lastEsp32Ping > 3000) {
      lastEsp32Ping = millis();
      socketIO.sendEVENT("[\"esp32_ping\",{\"device\":\"CyberHand ESP32\"}]");
    }
  }

  if (millis() - lastStatusPrint > 10000) {
    lastStatusPrint = millis();
    Serial.print("📶 Wi-Fi: ");
    Serial.print(WiFi.status() == WL_CONNECTED ? "OK" : "OFF");
    Serial.print(" | Socket.IO: ");
    Serial.print(socketConnected ? "OK" : "OFF");
    Serial.print(" | Target: ");
    Serial.print(use_ssl ? "wss://" : "ws://");
    Serial.print(cleanHost(server_host));
    Serial.print(":");
    Serial.println(server_port);
  }

  // Smoothing servo 100 Hz
  static unsigned long lastUpdateTime = 0;
  if (millis() - lastUpdateTime >= 10) {
    lastUpdateTime = millis();
    for (int i = 0; i < 5; i++) {
      float diff = targetPulses[i] - currentPulses[i];
      if (abs(diff) > 0.1) {
        currentPulses[i] += diff * SMOOTH_FACTOR;
        pwm.setPWM(servoPins[i], 0, round(currentPulses[i]));
      }
    }
  }
}
