# 🦾 VECTRA // CYBERHAND AI INTERFACE

VECTRA (Vectra AI Interface) adalah sistem kontrol lengan robotik (CyberHand) berbasis visi komputer (MediaPipe) yang memungkinkan kontrol jari robot secara real-time melalui kamera. Project ini dikembangkan untuk kebutuhan riset dan edukasi oleh **SD MUHAMMADIYAH LAMONGAN (SDMUHLA)**.

## 🌟 Fitur Utama
- **Real-time Hand Tracking**: Menggunakan MediaPipe Hands untuk mendeteksi gestur jari secara akurat.
- **WebSocket Communication**: Komunikasi low-latency antara server Python (Brain) dan ESP32 (Actuator).
- **Web Dashboard**: Antarmuka kontrol berbasis web yang futuristik dengan fitur kalibrasi servo.
- **Auto-Calibration**: Pengaturan Nilai Min, Max, dan Reverse servo langsung dari browser.
- **Local & Cloud Ready**: Dapat dijalankan di jaringan lokal WIFI atau melalui internet (Cloudflare Tunnel).

---

## 🛠️ Spesifikasi Hardware (Rekomendasi)
1. **Microcontroller**: ESP32 (NodeMCU/DevKit).
2. **Servo Driver**: PCA9685 16-Channel PWM Driver.
3. **Servo**: 5x Servo (SG90 atau MG90S) untuk setiap jari.
4. **Power Supply**: 5V 2A-5A (Disarankan terpisah dari ESP32 untuk menghindari noise/reboot).
5. **Kamera**: Webcam Laptop atau USB Webcam (untuk tracking jari).

### Skema Wiring (I2C)
| ESP32 Pin | PCA9685 Pin | Keterangan |
|-----------|-------------|------------|
| GPIO 21   | SDA         | I2C Data   |
| GPIO 22   | SCL         | I2C Clock  |
| 3.3V      | VCC         | Power Logic|
| GND       | GND         | Ground     |

---

## 💻 Instalasi Software

### 1. Persiapan Server (Python)
Pastikan Anda memiliki Python 3.9+ terinstall.

```bash
# Clone repository
git clone https://github.com/username/vectra.git
cd vectra

# Install dependensi
pip install -r requirements.txt
```

### 2. Konfigurasi ESP32 (Arduino IDE)
- Buka file `Vectra_Firmware/Vectra_Firmware.ino`.
- Install library berikut melalui Library Manager:
    - `Adafruit PWMServoDriver`
    - `WebSockets` (by Markus Sattler)
    - `ArduinoJson`
- Upload kode ke ESP32 Anda.

---

## 🚀 Cara Menjalankan (Mode Lokal)

### Langkah 1: Jalankan Server Python
Jalankan script `local/local.py` untuk memulai server lokal dengan panduan otomatis.
```bash
python local/local.py
```
Catat **IP Lokal** yang muncul di terminal (misal: `192.168.18.15`).

### Langkah 2: Hubungkan ESP32 ke Jaringan
1. Nyalakan ESP32.
2. Cari WiFi bernama **"CyberHand-Robot"** dengan password `password123`.
3. Buka browser dan akses `http://192.168.4.1`.
4. Masukkan **SSID** dan **Password** WiFi rumah Anda.
5. Masukkan **Domain / IP Server Python** (gunakan IP yang dicatat dari Langkah 1).
6. Masukkan **Port** (default: `5000`).
7. Klik **Simpan & Terapkan**. ESP32 akan reboot dan mencoba terhubung ke server.

### Langkah 3: Buka Dashboard
1. Buka browser di laptop Anda dan akses `http://localhost:5000`.
2. Masukkan password dashboard: `vectra123` (default).
3. Klik **INIT CAMERA** untuk memulai tracking.

---

## ⚙️ Kalibrasi
Anda dapat mengatur pergerakan setiap jari melalui panel **Actuator Calibration** di dashboard:
- **MIN/MAX**: Mengatur batas rentang gerak servo agar tidak melebihi fisik mekanik.
- **REVERSE**: Jika servo terpasang terbalik, centang opsi ini agar arah gerak sesuai dengan jari Anda.
- Nilai kalibrasi akan otomatis tersimpan di file `calibration.json`.

---

## 👨‍💻 Kontributor
- **SD MUHAMMADIYAH LAMONGAN** - *Research & Development* | [sdmuhla.sch.id](https://sdmuhla.sch.id)
- **Zahruddin Fanani** - *Developer* | [seefan.my.id](https://seefan.my.id)

---
*VECTRA is an Open Source Project for Educational Purpose.*
