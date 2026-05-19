import time
import json
import os
import threading
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit

# ==========================================
# 1. CONFIGURATION & FILE MANAGEMENT
# ==========================================
JSON_FILE = "calibration.json"
jari_names = ["Jempol", "Telunjuk", "Tengah", "Manis", "Kelingking"]

default_calibration = {name: {"min": 130, "max": 490} for name in jari_names}

def load_calibration():
    if os.path.exists(JSON_FILE):
        with open(JSON_FILE, "r") as f: return json.load(f)
    return default_calibration.copy()

def save_calibration(data):
    with open(JSON_FILE, "w") as f: json.dump(data, f, indent=4)

calibration_data = load_calibration()

# WebSocket/Socket.IO Setup untuk Komunikasi HP dan ESP32
# Tidak ada TCP server lagi. ESP32 menjadi client Socket.IO yang konek keluar ke domain Cloudflare Tunnel.
esp32_sid = None
esp32_ip = ""
lock = threading.Lock()

# Flask & SocketIO Setup
app = Flask(__name__)
app.config['SECRET_KEY'] = 'vectra_sdmuhla_key'
# async_mode=threading supaya mudah jalan di Windows tanpa eventlet/gevent
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ==========================================
# 2. SOCKET.IO: REGISTRASI ESP32
# ==========================================
@socketio.on('connect')
def on_connect():
    print(f"🔗 Client Socket.IO terhubung: {request.sid} dari {request.remote_addr}")

@socketio.on('disconnect')
def on_disconnect():
    global esp32_sid, esp32_ip
    with lock:
        if request.sid == esp32_sid:
            print("⚠️ ESP32 terputus dari WebSocket")
            esp32_sid = None
            esp32_ip = ""

@socketio.on('register_esp32')
def register_esp32(data=None):
    """Dipanggil oleh ESP32 setelah berhasil connect ke Socket.IO."""
    global esp32_sid, esp32_ip
    with lock:
        esp32_sid = request.sid
        esp32_ip = request.remote_addr or "ESP32"
    print(f"🤖 ESP32 terdaftar via WebSocket: SID={esp32_sid}, IP={esp32_ip}")
    emit('registered', {'ok': True, 'message': 'ESP32 registered'})

# ==========================================
# 3. WEBSOCKET: MENERIMA DATA DARI HP & FORWARD KE ESP32
# ==========================================
@socketio.on('send_pulses')
def handle_pulses_from_phone(data):
    """
    Dipanggil browser HP sekitar 30 FPS.
    Data langsung diteruskan ke ESP32 melalui Socket.IO, bukan TCP.
    Format event ke ESP32: pulses -> {"pulses": [130, 135, 130, 135, 130]}
    """
    global esp32_sid
    pulses = data.get('pulses', []) if isinstance(data, dict) else []

    if len(pulses) != 5:
        return

    try:
        pulses = [int(x) for x in pulses]
    except Exception:
        return

    with lock:
        sid = esp32_sid

    if sid:
        socketio.emit('pulses', {'pulses': pulses}, to=sid)

# ==========================================
# 4. TAILWIND + MEDIAPIPE EDGE AI JAVASCRIPT UI (VECTRA BRANDING)
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VECTRA // SDMUHLA Robotics</title>
    <script src="https://cdn.tailwindcss.com"></script>
    
    <!-- MediaPipe & SocketIO Libraries -->
    <script src="https://cdn.jsdelivr.net/npm/@mediapipe/camera_utils/camera_utils.js" crossorigin="anonymous"></script>
    <script src="https://cdn.jsdelivr.net/npm/@mediapipe/drawing_utils/drawing_utils.js" crossorigin="anonymous"></script>
    <script src="https://cdn.jsdelivr.net/npm/@mediapipe/hands/hands.js" crossorigin="anonymous"></script>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>

    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@300;400;600;800&display=swap');
        
        body { font-family: 'Inter', sans-serif; }
        .font-mono { font-family: 'JetBrains Mono', monospace; }
        
        .mirrored { transform: scaleX(-1); }
        
        /* Custom Minimalist Sliders */
        input[type=range] {
            -webkit-appearance: none;
            background: transparent;
        }
        input[type=range]::-webkit-slider-thumb {
            -webkit-appearance: none;
            height: 14px; width: 8px;
            border-radius: 2px;
            background: #ffffff;
            cursor: pointer;
            box-shadow: 0 0 5px rgba(255,255,255,0.5);
            margin-top: -6px; /* Center thumb on track */
        }
        input[type=range]::-webkit-slider-runnable-track {
            width: 100%; height: 2px;
            cursor: pointer;
            background: #27272a; /* zinc-800 */
            border-radius: 1px;
        }
        .slider-cyan::-webkit-slider-thumb { background: #06b6d4; box-shadow: 0 0 8px rgba(6, 182, 212, 0.8); }
        .slider-rose::-webkit-slider-thumb { background: #f43f5e; box-shadow: 0 0 8px rgba(244, 63, 94, 0.8); }
        
        /* Subtle glow for container */
        .glass-panel {
            background: rgba(24, 24, 27, 0.7);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.05);
        }
        
        .custom-scrollbar::-webkit-scrollbar { width: 4px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: #27272a; border-radius: 2px; }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #06b6d4; }
    </style>
</head>
<body class="bg-[#09090b] text-zinc-300 min-h-screen overflow-x-hidden selection:bg-cyan-500/30 selection:text-cyan-50 flex flex-col">
    <!-- Container utama dibikin flex h-screen agar layout tidak melar -->
    <div class="max-w-[1400px] w-full mx-auto px-4 py-6 h-screen flex flex-col min-h-0">
        
        <!-- HEADER (VECTRA BRANDING) -->
        <header class="flex flex-col md:flex-row justify-between items-end mb-6 border-b border-zinc-800 pb-4 gap-4 flex-shrink-0">
            <div>
                <h1 class="text-3xl font-extrabold tracking-widest bg-clip-text text-transparent bg-gradient-to-r from-cyan-400 to-blue-500">
                    VECTRA <span class="font-light text-zinc-100">// AI INTERFACE</span>
                </h1>
                <p class="text-[10px] tracking-[0.2em] text-zinc-500 uppercase mt-1">
                    RESEARCH & DEVELOPMENT BY <span class="text-cyan-400 font-semibold">SDMUHLA</span>
                </p>
                <p class="text-[9px] tracking-[0.1em] text-zinc-600 uppercase mt-0.5">
                    SD MUHAMMADIYAH LAMONGAN
                </p>
            </div>
            
            <div class="flex items-center gap-6">
                <!-- Status -->
                <div class="flex items-center gap-2">
                    <span class="text-[10px] text-zinc-500 font-mono uppercase tracking-widest">Sys.Status</span>
                    <div id="status_indicator" class="flex items-center gap-2 px-2 py-1 bg-zinc-900 border border-zinc-800 rounded">
                        <span id="status_dot" class="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse"></span>
                        <span id="esp32_status" class="text-[10px] font-mono text-zinc-400">WAITING</span>
                    </div>
                </div>
                
                <!-- Camera Button -->
                <button id="camToggle" onclick="toggleCamera()" class="group relative px-5 py-2 bg-zinc-900 hover:bg-cyan-950 border border-zinc-800 hover:border-cyan-500/50 transition-all rounded">
                    <div class="absolute inset-0 w-0 bg-cyan-500/10 transition-all duration-300 ease-out group-hover:w-full"></div>
                    <span class="relative text-xs font-mono text-zinc-300 group-hover:text-cyan-400 tracking-widest uppercase flex items-center gap-2">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                        Init Camera
                    </span>
                </button>
            </div>
        </header>

        <!-- LAYOUT 3 KOLOM FIXED -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 xl:gap-8 flex-grow min-h-0 overflow-hidden pb-4">
            
            <!-- PANEL 1: CAMERA VIEWPORT (KIRI) -->
            <div class="lg:col-span-4 h-full flex flex-col min-h-0">
                <div class="glass-panel p-4 rounded-xl flex flex-col items-center h-full min-h-0">
                    <div class="flex w-full justify-between items-center mb-3 flex-shrink-0">
                        <h2 class="text-[10px] font-mono text-zinc-400 tracking-widest uppercase">Viewport.Feed</h2>
                        <span id="fps_counter" class="text-[10px] font-mono text-cyan-400 bg-cyan-400/10 px-1.5 py-0.5 rounded">0 FPS</span>
                    </div>
                    
                    <div class="relative w-full flex-grow bg-zinc-950 rounded-lg overflow-hidden border border-zinc-800/80 min-h-0 flex items-center justify-center">
                        <video id="input_video" class="hidden" playsinline></video>
                        <canvas id="output_canvas" class="w-full h-full object-contain mirrored opacity-90"></canvas>
                        
                        <!-- Overlay HUD -->
                        <div class="absolute top-2 left-2 w-4 h-4 border-t border-l border-cyan-500/50"></div>
                        <div class="absolute top-2 right-2 w-4 h-4 border-t border-r border-cyan-500/50"></div>
                        <div class="absolute bottom-2 left-2 w-4 h-4 border-b border-l border-cyan-500/50"></div>
                        <div class="absolute bottom-2 right-2 w-4 h-4 border-b border-r border-cyan-500/50"></div>
                        
                        <!-- Loading State -->
                        <div id="loadingAI" class="absolute inset-0 flex flex-col items-center justify-center bg-zinc-950/80 backdrop-blur-sm z-10 hidden">
                            <svg class="animate-spin h-6 w-6 text-cyan-500 mb-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                            <span class="text-cyan-400 font-mono tracking-widest text-[10px] uppercase">Booting VECTRA Core...</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- PANEL 2: REAL-TIME DATA LOG TERMINAL (TENGAH) -->
            <div class="lg:col-span-3 h-full flex flex-col min-h-0">
                <div class="glass-panel p-4 rounded-xl flex flex-col h-full min-h-0">
                    <div class="flex w-full justify-between items-center mb-2 border-b border-zinc-800 pb-2 flex-shrink-0">
                        <h2 class="text-[10px] font-mono text-zinc-400 tracking-widest uppercase flex items-center gap-2">
                            <svg class="w-3.5 h-3.5 text-cyan-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 6h16M4 12h16M4 18h7"></path></svg>
                            Stream_Log
                        </h2>
                        <button onclick="clearLog()" class="text-[9px] font-mono text-zinc-500 hover:text-cyan-400 transition-colors uppercase tracking-widest">Clear</button>
                    </div>
                    
                    <!-- INFORMASI TAMBAHAN FORMAT DATA -->
                    <div class="text-[10px] font-mono text-zinc-400 mb-2 pb-2 border-b border-zinc-800/50 leading-relaxed flex-shrink-0">
                        <span class="text-cyan-500/70 font-semibold tracking-wider">FORMAT:</span> [Jempol, Telunjuk, Tengah, Manis, Keling]<br>
                        <span class="text-zinc-600">Terbaru di urutan paling atas.</span>
                    </div>

                    <!-- Kunci ukuran list log -->
                    <div id="terminal_log" class="flex-grow overflow-y-auto h-0 min-h-0 text-[11px] font-mono text-cyan-500/90 space-y-1.5 pr-2 custom-scrollbar">
                        <div class="text-zinc-600 italic mt-1">Standby. Menunggu data AI 30FPS...</div>
                    </div>
                </div>
            </div>

            <!-- PANEL 3: CALIBRATION MATRIX (KANAN) -->
            <div class="lg:col-span-5 h-full flex flex-col min-h-0">
                <div class="glass-panel p-6 rounded-xl flex flex-col justify-center h-full min-h-0 overflow-y-auto custom-scrollbar">
                    <div class="flex justify-between items-end mb-6 border-b border-zinc-800 pb-2 flex-shrink-0">
                        <h2 class="text-[10px] font-mono text-zinc-400 tracking-widest uppercase">Actuator.Calibration</h2>
                        <span class="text-[10px] font-mono text-zinc-600">PULSE WIDTH (μs)</span>
                    </div>
                    
                    <div class="flex flex-col gap-3 flex-grow">
                        {% for name in jari_names %}
                        <div class="group relative px-4 py-3 rounded-lg bg-zinc-900/50 border border-zinc-800/50 hover:border-zinc-700 transition-colors">
                            <div class="absolute left-0 top-0 bottom-0 w-0.5 bg-zinc-800 group-hover:bg-cyan-500/50 transition-colors rounded-l-lg"></div>
                            
                            <div class="flex flex-col xl:flex-row xl:items-center gap-4">
                                <span class="text-xs font-mono tracking-widest text-zinc-300 uppercase xl:w-20">{{ name }}</span>
                                
                                <div class="flex-grow grid grid-cols-2 gap-4">
                                    <!-- Min Slider -->
                                    <div class="flex flex-col justify-center">
                                        <div class="flex justify-between text-[10px] font-mono text-zinc-500 mb-1.5 uppercase">
                                            <span>MIN (0°)</span>
                                            <span class="text-cyan-400" id="{{name}}_min_txt">{{cal_data[name]['min']}}</span>
                                        </div>
                                        <input type="range" min="100" max="250" value="{{cal_data[name]['min']}}" 
                                            class="w-full custom-slider slider-cyan" 
                                            oninput="updateCal('{{name}}', 'min', this.value)">
                                    </div>
                                    
                                    <!-- Max Slider -->
                                    <div class="flex flex-col justify-center">
                                        <div class="flex justify-between text-[10px] font-mono text-zinc-500 mb-1.5 uppercase">
                                            <span>MAX (180°)</span>
                                            <span class="text-rose-400" id="{{name}}_max_txt">{{cal_data[name]['max']}}</span>
                                        </div>
                                        <input type="range" min="400" max="600" value="{{cal_data[name]['max']}}" 
                                            class="w-full custom-slider slider-rose" 
                                            oninput="updateCal('{{name}}', 'max', this.value)">
                                    </div>
                                </div>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                    
                    <div class="mt-4 text-right flex-shrink-0">
                        <p class="text-[9px] font-mono text-zinc-600 uppercase">Data auto-saves to JSON via Socket</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        let calData = {{ cal_data | tojson | safe }};
        const jariNames = ["Jempol", "Telunjuk", "Tengah", "Manis", "Kelingking"];
        
        let prevAngles = [0.0, 0.0, 0.0, 0.0, 0.0];
        const ALPHA = 0.40;
        let lastFrameTime = performance.now();
        let frameCount = 0;

        const terminalLog = document.getElementById('terminal_log');
        let logCount = 0;
        const MAX_LOG_LINES = 25; // Batas memori agar UI HP tidak lag

        function addLog(pulses) {
            const now = new Date();
            const timeStr = now.getSeconds().toString().padStart(2, '0') + '.' + now.getMilliseconds().toString().padStart(3, '0');
            
            if (logCount === 0) terminalLog.innerHTML = ''; // Hapus teks standby
            
            const line = document.createElement('div');
            line.innerHTML = `<span class="text-zinc-600">[${timeStr}]</span> <span class="text-zinc-500">TX:</span> <span class="text-cyan-400">${pulses.join('<span class="text-zinc-700">,</span> ')}</span>`;
            
            // Masukkan data terbaru di PALING ATAS
            terminalLog.prepend(line);
            logCount++;
            
            // Hapus log paling BAWAH (terlama) jika melebihi batas 25 baris
            if (terminalLog.childElementCount > MAX_LOG_LINES) {
                terminalLog.removeChild(terminalLog.lastChild);
            }
        }

        function clearLog() {
            terminalLog.innerHTML = '<div class="text-zinc-600 italic mt-1">Standby. Menunggu data...</div>';
            logCount = 0;
        }

        function updateCal(jari, type, val) {
            document.getElementById(jari + "_" + type + "_txt").innerText = val;
            calData[jari][type] = parseInt(val); 
            fetch('/update', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({jari: jari, type: type, value: parseInt(val)})
            });
        }

        function mapRange(value, in_min, in_max, out_min, out_max) {
            value = Math.max(Math.min(value, in_max), in_min);
            return ((value - in_min) * (out_max - out_min) / (in_max - in_min)) + out_min;
        }

        // FUNGSI VEKTOR INVARIAN ROTASI 
        function getJointAngle4Points(p1, p2, p3, p4) {
            let v1 = {x: p2.x - p1.x, y: p2.y - p1.y, z: p2.z - p1.z};
            let v2 = {x: p4.x - p3.x, y: p4.y - p3.y, z: p4.z - p3.z};
            
            let dotProd = v1.x * v2.x + v1.y * v2.y + v1.z * v2.z;
            let mag1 = Math.sqrt(v1.x**2 + v1.y**2 + v1.z**2);
            let mag2 = Math.sqrt(v2.x**2 + v2.y**2 + v2.z**2);
            
            if (mag1 * mag2 === 0) return 0;
            let cosineAngle = Math.max(-1.0, Math.min(1.0, dotProd / (mag1 * mag2)));
            return (Math.acos(cosineAngle) * 180.0) / Math.PI;
        }

        const videoElement = document.getElementById('input_video');
        const canvasElement = document.getElementById('output_canvas');
        const canvasCtx = canvasElement.getContext('2d');
        let cameraStarted = false;
        let cameraObj = null;

        const hands = new Hands({locateFile: (file) => {
            return `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`;
        }});

        hands.setOptions({
            maxNumHands: 1,
            modelComplexity: 1,
            minDetectionConfidence: 0.7,
            minTrackingConfidence: 0.7
        });

        hands.onResults(onResults);

        function onResults(results) {
            frameCount++;
            let now = performance.now();
            if (now - lastFrameTime >= 1000) {
                document.getElementById('fps_counter').innerText = frameCount + " FPS";
                frameCount = 0;
                lastFrameTime = now;
            }

            canvasCtx.save();
            canvasCtx.clearRect(0, 0, canvasElement.width, canvasElement.height);
            canvasCtx.drawImage(results.image, 0, 0, canvasElement.width, canvasElement.height);
            
            if (results.multiHandLandmarks && results.multiHandLandmarks.length > 0) {
                const lm = results.multiHandLandmarks[0];
                
                // VECTRA HUD Styling
                drawConnectors(canvasCtx, lm, HAND_CONNECTIONS, {color: 'rgba(6, 182, 212, 0.5)', lineWidth: 2});
                drawLandmarks(canvasCtx, lm, {color: '#22d3ee', lineWidth: 1, radius: 2});

                let rawAngles = [];
                
                // 1. JEMPOL (Double-Joint Sensitivity)
                let thumbBend1 = getJointAngle4Points(lm[1], lm[2], lm[2], lm[3]); 
                let thumbBend2 = getJointAngle4Points(lm[2], lm[3], lm[3], lm[4]); 
                let totalThumbBend = thumbBend1 + thumbBend2;
                rawAngles.push(mapRange(totalThumbBend, 15, 90, 0, 180));

                // 2. 4 JARI LAINNYA (Occlusion Guard)
                const fingersData = [[5,6,7,8], [9,10,11,12], [13,14,15,16], [17,18,19,20]];
                for (let idx of fingersData) {
                    let angle = getJointAngle4Points(lm[idx[0]], lm[idx[1]], lm[idx[2]], lm[idx[3]]);
                    if (lm[idx[3]].y > lm[idx[1]].y && angle > 110) {
                        rawAngles.push(180.0); // Terkunci mengepal
                    } else {
                        rawAngles.push(mapRange(angle, 15, 145, 0, 180));
                    }
                }

                // Filtering dan Kalkulasi ke Pulsa Servo
                let pulsesToSend = [];
                for(let i=0; i<5; i++){
                    prevAngles[i] = (ALPHA * rawAngles[i]) + ((1 - ALPHA) * prevAngles[i]);
                    let cMin = calData[jariNames[i]].min;
                    let cMax = calData[jariNames[i]].max;
                    let pulse = cMin + (prevAngles[i] * (cMax - cMin) / 180.0);
                    pulsesToSend.push(Math.round(pulse));
                }

                socket.emit('send_pulses', {pulses: pulsesToSend});
                addLog(pulsesToSend); // Tampilkan secara real-time di UI
            }
            canvasCtx.restore();
        }

        function toggleCamera() {
            const btn = document.getElementById('camToggle');
            const loading = document.getElementById('loadingAI');
            const spanText = btn.querySelector('span');
            
            if(!cameraStarted) {
                loading.classList.remove('hidden');
                spanText.innerHTML = `<svg class="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> BOOTING...`;
                
                const vidWidth = window.innerWidth < 640 ? 480 : 640;
                const vidHeight = window.innerWidth < 640 ? 640 : 480;

                cameraObj = new Camera(videoElement, {
                    onFrame: async () => {
                        await hands.send({image: videoElement});
                        if(loading.classList.contains('hidden') === false){
                            loading.classList.add('hidden');
                            spanText.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M6 18L18 6M6 6l12 12"></path></svg> HALT CAM`;
                            spanText.className = "relative text-xs font-mono text-rose-400 group-hover:text-rose-300 tracking-widest uppercase flex items-center gap-2";
                            btn.querySelector('div').className = "absolute inset-0 w-0 bg-rose-500/10 transition-all duration-300 ease-out group-hover:w-full";
                            btn.className = "group relative px-5 py-2 bg-zinc-900 hover:bg-rose-950 border border-zinc-800 hover:border-rose-500/50 transition-all rounded";
                        }
                    },
                    width: vidWidth,
                    height: vidHeight
                });
                cameraObj.start();
                cameraStarted = true;
            } else {
                cameraObj.stop();
                canvasCtx.clearRect(0, 0, canvasElement.width, canvasElement.height);
                spanText.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"></path></svg> INIT CAM`;
                spanText.className = "relative text-xs font-mono text-zinc-300 group-hover:text-cyan-400 tracking-widest uppercase flex items-center gap-2";
                btn.querySelector('div').className = "absolute inset-0 w-0 bg-cyan-500/10 transition-all duration-300 ease-out group-hover:w-full";
                btn.className = "group relative px-5 py-2 bg-zinc-900 hover:bg-cyan-950 border border-zinc-800 hover:border-cyan-500/50 transition-all rounded";
                cameraStarted = false;
                document.getElementById('fps_counter').innerText = "0 FPS";
                clearLog(); // Hapus log ketika kamera mati
            }
        }

        async function checkStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                const dot = document.getElementById('status_dot');
                const txt = document.getElementById('esp32_status');
                
                if(data.connected) {
                    dot.className = "w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.8)]";
                    txt.innerText = data.ip;
                    txt.className = "text-[10px] font-mono text-cyan-400";
                } else {
                    dot.className = "w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse";
                    txt.innerText = "WAITING";
                    txt.className = "text-[10px] font-mono text-zinc-500";
                }
            } catch(e) {}
        }
        setInterval(checkStatus, 2000);
    </script>
</body>
</html>
"""

# ==========================================
# 5. FLASK WEB ROUTES & API
# ==========================================
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, jari_names=jari_names, cal_data=calibration_data)

@app.route('/update', methods=['POST'])
def update_data():
    global calibration_data
    req = request.get_json()
    with lock:
        calibration_data[req['jari']][req['type']] = req['value']
        save_calibration(calibration_data)
    return jsonify({"status": "success"})

@app.route('/api/status', methods=['GET'])
def get_status():
    global esp32_sid, esp32_ip
    with lock:
        connected = esp32_sid is not None
        ip = esp32_ip if connected else ""
    return jsonify({"connected": connected, "ip": ip})

if __name__ == '__main__':
    print("\n========================================================")
    print("🚀 VECTRA SDMUHLA: EDGE AI SERVER AKTIF!")
    print("========================================================")
    
    # Jalankan TCP Server untuk ESP32
    t_tcp = threading.Thread(target=tcp_server_loop)
    t_tcp.daemon = True
    t_tcp.start()

    print(f"📡 Robot VECTRA ESP32 Diharapkan konek ke Port TCP: {TCP_PORT}")
    print(f"🌐 1. Buka HP/Tablet untuk kendali kamera")
    print(f"🔗 2. Akses WAJIB menggunakan HTTPS: https://[IP_LAPTOP_ANDA]:5000")
    print(f"⚠️   (Jika browser protes keamanan, klik Advanced -> Proceed)")
    print("========================================================\n")

    # JALANKAN WEBSERVER DENGAN SSL/HTTPS AGAR KAMERA HP BISA DIAKSES!
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, ssl_context='adhoc')