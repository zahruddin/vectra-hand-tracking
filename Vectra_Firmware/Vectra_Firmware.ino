#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h> 

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();
// Port 0=Jempol, 1=Telunjuk, 2=Tengah, 3=Manis, 4=Kelingking
const int servoPins[5] = {0, 1, 2, 3, 4}; 

// Objek Web Server (Port 80) dan TCP Client (Jalur Data)
WebServer server(80);
Preferences pref;
WiFiClient client; 

// Variabel Konfigurasi Dinamis (Akan ditimpa oleh data dari Flash Memory)
String wifi_ssid = "";
String wifi_pass = "";
String server_ip = "192.168.18.13";
int server_port  = 8080;
String server_path = ""; 

// Variabel pergerakan servo (Menggunakan Float untuk Easing)
float currentPulses[5] = {130.0, 135.0, 130.0, 135.0, 130.0}; 
float targetPulses[5]  = {130.0, 135.0, 130.0, 135.0, 130.0};
const float SMOOTH_FACTOR = 0.15; // Kehalusan gerakan
String inputBuffer = "";

// ==========================================
// KODE HTML UNTUK WEB DASHBOARD ESP32
// ==========================================
void handleRoot() {
  String html = "<!DOCTYPE html><html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'>";
  html += "<title>CyberHand Config</title>";
  html += "<script src='https://cdn.tailwindcss.com'></script></head>";
  html += "<body class='bg-gray-950 text-gray-100 font-sans min-h-screen flex items-center justify-center p-4'>";
  html += "<div class='max-w-md w-full bg-gray-900 border border-gray-800 p-6 rounded-2xl shadow-2xl'>";
  html += "<h1 class='text-2xl font-black text-center bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-indigo-400 mb-2'>🦾 CYBERHAND CONFIG</h1>";
  html += "<p class='text-xs text-gray-400 text-center mb-6'>Halaman ini selalu aktif di jaringan lokal & AP ESP32</p>";
  
  // Status Box
  html += "<div class='bg-gray-950 p-3 rounded-xl border border-gray-800 text-xs space-y-1 mb-6'>";
  html += "<div>🔴 <span class='text-gray-400'>Status Wi-Fi:</span> <span class='font-bold " + String(WiFi.status() == WL_CONNECTED ? "text-green-400" : "text-red-400") + "'>" + String(WiFi.status() == WL_CONNECTED ? "TERHUBUNG" : "TERPUTUS") + "</span></div>";
  html += "<div>🏠 <span class='text-gray-400'>Wi-Fi Terhubung:</span> <span class='font-mono'>" + WiFi.SSID() + "</span></div>";
  html += "<div>📍 <span class='text-gray-400'>IP Lokal STA:</span> <span class='font-mono text-blue-400'>" + WiFi.localIP().toString() + "</span></div>";
  html += "<div>🖥️ <span class='text-gray-400'>Target Server:</span> <span class='font-mono text-yellow-400'>" + server_ip + ":" + String(server_port) + "</span></div>";
  html += "</div>";

  // Form Input
  html += "<form action='/save' method='POST' class='space-y-4'>";
  html += "<div><label class='block text-xs font-bold text-gray-400 uppercase mb-1'>SSID Wi-Fi Rumah</label><input type='text' name='ssid' value='" + wifi_ssid + "' class='w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500'></div>";
  html += "<div><label class='block text-xs font-bold text-gray-400 uppercase mb-1'>Password Wi-Fi</label><input type='password' name='pass' value='" + wifi_pass + "' class='w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500'></div>";
  html += "<div><label class='block text-xs font-bold text-gray-400 uppercase mb-1'>IP / Domain Home Server</label><input type='text' name='ip' value='" + server_ip + "' class='w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500'></div>";
  html += "<div><label class='block text-xs font-bold text-gray-400 uppercase mb-1'>Port Server TCP</label><input type='number' name='port' value='" + String(server_port) + "' class='w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500'></div>";
  html += "<button type='submit' class='w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-2.5 rounded-lg shadow-lg transition duration-150 mt-2'>Simpan & Terapkan</button>";
  html += "</form></div></body></html>";
  
  server.send(200, "text/html", html);
}

void handleSave() {
  if (server.method() == HTTP_POST) {
    wifi_ssid   = server.arg("ssid");
    wifi_pass   = server.arg("pass");
    server_ip   = server.arg("ip");
    server_port = server.arg("port").toInt();
    server_path = server.arg("path");

    // Simpan ke Memori Flash permanen
    pref.begin("cyberhand", false);
    pref.putString("ssid", wifi_ssid);
    pref.putString("pass", wifi_pass);
    pref.putString("ip", server_ip);
    pref.putInt("port", server_port);
    pref.end();

    String html = "<html><body style='background:#0f172a;color:#f8fafc;font-family:sans-serif;text-align:center;padding-top:50px;'>";
    html += "<h2>✅ Konfigurasi Berhasil Disimpan!</h2><p>ESP32 sedang mencoba menghubungkan ulang sistem...</p>";
    html += "<script>setTimeout(function(){window.location.href='/';}, 3000);</script></body></html>";
    server.send(200, "text/html", html);
    
    delay(1000);
    
    // Putuskan koneksi lama dan hubungkan ulang
    client.stop();
    WiFi.disconnect();
    Serial.println("\n🔄 Mencoba terhubung ke Wi-Fi baru: " + wifi_ssid);
    WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("\n=== BOOTING CYBERHAND ESP32 ===");
  
  pwm.begin();
  pwm.setOscillatorFrequency(27000000);
  pwm.setPWMFreq(50); 
  delay(20);

  // Set posisi awal servo (Siaga)
  for (int i = 0; i < 5; i++) {
    pwm.setPWM(servoPins[i], 0, (int)currentPulses[i]);
  }

  // Load konfigurasi dari Memori Internal
  pref.begin("cyberhand", true);
  wifi_ssid   = pref.getString("ssid", "");
  wifi_pass   = pref.getString("pass", "");
  server_ip   = pref.getString("ip", "192.168.18.13");
  server_port = pref.getInt("port", 8080);
  pref.end();

  // Aktifkan DUAL MODE (Access Point + Station) tanpa NAT
  WiFi.mode(WIFI_AP_STA);
  
  // 1. Sebarkan Wi-Fi Sendiri (Selalu Aktif untuk Konfigurasi Darurat)
  WiFi.softAP("CyberHand-Robot", "password123");
  Serial.print("📡 Hotspot Mandiri Aktif! Akses config di: "); 
  Serial.println(WiFi.softAPIP());

  // 2. Hubungkan ke Wi-Fi Rumah (Jika data tersimpan)
  if (wifi_ssid != "") {
    WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());
    Serial.println("🔄 Mencoba tersambung ke Wi-Fi: " + wifi_ssid);
  } else {
    Serial.println("⚠️ Belum ada data Wi-Fi tersimpan. Silakan hubungkan ke Hotspot ESP32 untuk konfigurasi.");
  }

  // Mulai Web Server Internal
  server.on("/", handleRoot);
  server.on("/save", handleSave);
  server.begin();
  Serial.println("🌐 Web Server Internal Siaga di Port 80");
}

void loop() {
  // Selalu pantau jika ada yang membuka halaman web konfigurasi
  server.handleClient();

  // ==========================================
  // JALUR DATA TCP SOCKET KE PYTHON (AUTO-RECONNECT)
  // ==========================================
  if (WiFi.status() == WL_CONNECTED) {
    if (!client.connected()) {
      static unsigned long lastReconnectAttempt = 0;
      if (millis() - lastReconnectAttempt > 5000) { 
        lastReconnectAttempt = millis();
        Serial.print("🔍 Mencari Python TCP Server di -> "); 
        Serial.print(server_ip); Serial.print(":"); Serial.println(server_port);
        
        if (client.connect(server_ip.c_str(), server_port)) {
          Serial.println("✅ TERHUBUNG KE SERVER PYTHON! Siap menerima data gerakan.");
        }
      }
    }
  }

  // ==========================================
  // BACA DATA STREAMING DARI PYTHON (Non-Blocking)
  // ==========================================
  while (client.available() > 0) {
    char rc = client.read();
    if (rc != '\n') {
      inputBuffer += rc;
    } else {
      // Terjemahkan string ke angka servo dan log ke Serial Monitor
      parseSerialPulses(inputBuffer);
      inputBuffer = "";
    }
  }

  // ==========================================
  // SMOOTHING INTERPOLASI SERVO MEKANIS (100 Hz)
  // ==========================================
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

// Fungsi untuk memecah string "130,480,130,480,130" menjadi Array Target
void parseSerialPulses(String data) {
  int idx = 0;
  int startPos = 0;
  
  // Variabel penampung untuk mencetak sudut ke Serial Monitor
  String logAngles = "📐 Sudut: ";
  
  for (int i = 0; i <= data.length(); i++) {
    if (data.charAt(i) == ',' || i == data.length()) {
      String part = data.substring(startPos, i);
      if (idx < 5) {
        float pulseVal = part.toFloat();
        
        // 1. Simpan nilai target pulsa untuk menggerakkan Servo (Dibatasi di rentang aman)
        targetPulses[idx] = constrain(pulseVal, 100.0, 550.0);
        
        // 2. KONVERSI KE DERAJAT (Hanya untuk Tampilan Serial Monitor)
        // Kita menggunakan rentang default kalibrasi MG90S (Min 130, Max 490) sebagai acuan konversi kasar
        float default_min = 130.0;
        float default_max = 490.0;
        
        float angle = ((pulseVal - default_min) * 180.0) / (default_max - default_min);
        // Batasi tampilan agar selalu berada di antara 0 - 180
        int finalAngle = constrain(round(angle), 0, 180);
        
        logAngles += String(finalAngle);
        if (idx < 4) logAngles += "°, ";
        else logAngles += "°";
      }
      startPos = i + 1;
      idx++;
    }
  }
  
  // Tampilkan data PWM Mentah beserta data Sudut yang sudah dikonversi
  Serial.print("📥 PWM: ");
  Serial.print(data);
  Serial.print("  |  ");
  Serial.println(logAngles);
}