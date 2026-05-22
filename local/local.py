import json
import os
import threading
import time
import socket
import shutil
from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO
from flask_sock import Sock

# =====================================================
# VECTRA / CYBERHAND PYTHON SERVER (LOCAL OPTIMIZED)
# =====================================================

JSON_FILE = "calibration.json"
EXAMPLE_FILE = "calibration.example.json"
jari_names = ["Jempol", "Telunjuk", "Tengah", "Manis", "Kelingking"]
default_calibration = {name: {"min": 130, "max": 490, "reverse": False} for name in jari_names}

def get_local_ip():
    """Mendeteksi IP local agar mudah dimasukkan ke config ESP32."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def load_calibration():
    # Jika file asli tidak ada tapi ada example, copy saja
    if not os.path.exists(JSON_FILE) and os.path.exists(EXAMPLE_FILE):
        print(f"ℹ️ Menginisialisasi {JSON_FILE} dari example.")
        shutil.copy(EXAMPLE_FILE, JSON_FILE)

    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            for name in jari_names:
                if name not in data:
                    data[name] = default_calibration[name].copy()
                if "min" not in data[name]:
                    data[name]["min"] = default_calibration[name]["min"]
                if "max" not in data[name]:
                    data[name]["max"] = default_calibration[name]["max"]
                if "reverse" not in data[name]:
                    data[name]["reverse"] = default_calibration[name]["reverse"]
                data[name]["reverse"] = bool(data[name]["reverse"])

            return data
        except Exception as e:
            print(f"⚠️ Gagal membaca calibration.json, pakai default. Error: {e}")

    return {name: value.copy() for name, value in default_calibration.items()}


def save_calibration(data):
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


calibration_data = load_calibration()

app = Flask(__name__)
# Gunakan secret key tetap untuk local agar session tidak hilang saat restart
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "vectra_sdmuhla_key_local_fixed")
VECTRA_PASSWORD = os.environ.get("VECTRA_PASSWORD", "vectra123")

# Socket.IO untuk browser/HP
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
)

# Plain WebSocket untuk ESP32
sock = Sock(app)

lock = threading.Lock()
esp32_ws = None
esp32_connected = False
esp32_ip = ""
esp32_last_seen = 0


# =====================================================
# ESP32 PLAIN WEBSOCKET: /esp32
# =====================================================
@sock.route("/esp32")
def esp32_socket(ws):
    global esp32_ws, esp32_connected, esp32_ip, esp32_last_seen

    with lock:
        esp32_ws = ws
        esp32_connected = True
        esp32_ip = request.remote_addr or "ESP32"
        esp32_last_seen = time.time()

    print(f"🤖 ESP32 terhubung via plain WebSocket /esp32, IP={esp32_ip}")

    try:
        ws.send(json.dumps({
            "type": "registered",
            "ok": True,
            "message": "ESP32 WebSocket connected"
        }))

        while True:
            msg = ws.receive()

            if msg is None:
                break

            try:
                data = json.loads(msg)
            except Exception:
                print(f"⚠️ Pesan ESP32 bukan JSON: {msg}")
                continue

            msg_type = data.get("type")

            with lock:
                esp32_last_seen = time.time()
                esp32_connected = True

            if msg_type == "register_esp32":
                print(f"🤖 ESP32 register: {data}")
                ws.send(json.dumps({
                    "type": "registered",
                    "ok": True
                }))
                ws.send(json.dumps({
                    "type": "servo_config",
                    "reverse": [bool(calibration_data[name].get("reverse", False)) for name in jari_names],
                    "min": [int(calibration_data[name].get("min", 130)) for name in jari_names],
                    "max": [int(calibration_data[name].get("max", 490)) for name in jari_names]
                }))

            elif msg_type == "ping":
                ws.send(json.dumps({
                    "type": "pong",
                    "server_time": time.time()
                }))

            else:
                print(f"ℹ️ Pesan ESP32: {data}")

    except Exception as e:
        print(f"⚠️ ESP32 WebSocket error: {e}")

    finally:
        with lock:
            if esp32_ws is ws:
                esp32_ws = None
                esp32_connected = False
                esp32_ip = ""
                esp32_last_seen = 0

        print("⚠️ ESP32 WebSocket terputus")


def send_to_esp32(payload):
    global esp32_ws, esp32_connected

    with lock:
        ws = esp32_ws
        connected = esp32_connected and ws is not None

    if not connected:
        return False

    try:
        ws.send(json.dumps(payload))
        return True
    except Exception as e:
        print(f"⚠️ Gagal kirim ke ESP32: {e}")
        with lock:
            esp32_connected = False
        return False


# =====================================================
# BROWSER SOCKET.IO
# =====================================================
@socketio.on("connect")
def on_connect():
    if not is_logged_in():
        print(f"⛔ Socket.IO browser ditolak, belum login: SID={request.sid}, IP={request.remote_addr}")
        return False
    print(f"🔗 Browser/Client Socket.IO terhubung: SID={request.sid}, IP={request.remote_addr}")


@socketio.on("disconnect")
def on_disconnect():
    print(f"ℹ️ Browser/Client Socket.IO terputus: SID={request.sid}")


@socketio.on("send_pulses")
def handle_pulses_from_phone(data):
    pulses = data.get("pulses", []) if isinstance(data, dict) else []

    if len(pulses) != 5:
        return

    try:
        pulses = [int(x) for x in pulses]
    except Exception:
        return

    pulses = [max(100, min(600, x)) for x in pulses]

    reverse_flags = [bool(calibration_data[name].get("reverse", False)) for name in jari_names]

    ok = send_to_esp32({
        "type": "pulses",
        "pulses": pulses,
        "reverse": reverse_flags
    })

    if not ok:
        # Jangan terlalu sering print, tapi berguna saat debugging awal.
        pass



# =====================================================
# SIMPLE PASSWORD LOGIN
# =====================================================
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VECTRA Login</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#09090b] text-zinc-100 min-h-screen flex items-center justify-center p-4">
    <form method="POST" class="w-full max-w-sm bg-zinc-900 border border-zinc-800 rounded-2xl p-6 shadow-2xl">
        <h1 class="text-2xl font-black tracking-widest text-cyan-400 text-center mb-1">VECTRA</h1>
        <p class="text-xs text-zinc-500 text-center mb-6 uppercase tracking-widest">Protected Dashboard</p>
        {% if error %}
        <div class="mb-4 text-xs text-rose-300 bg-rose-950/40 border border-rose-800 rounded-lg px-3 py-2">{{ error }}</div>
        {% endif %}
        <label class="block text-xs font-bold text-zinc-400 uppercase mb-1">Password</label>
        <input type="password" name="password" autofocus class="w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-500 mb-4">
        <button type="submit" class="w-full bg-cyan-600 hover:bg-cyan-500 text-white font-bold py-2.5 rounded-lg transition">Masuk</button>
    </form>
</body>
</html>
"""


def is_logged_in():
    return session.get("vectra_logged_in") is True


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == VECTRA_PASSWORD:
            session["vectra_logged_in"] = True
            return redirect(url_for("index"))
        return render_template_string(LOGIN_TEMPLATE, error="Password salah."), 401
    return render_template_string(LOGIN_TEMPLATE, error="")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =====================================================
# HTML DASHBOARD
# =====================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VECTRA // SDMUHLA Robotics</title>
    <script src="https://cdn.tailwindcss.com"></script>

    <script src="https://cdn.jsdelivr.net/npm/@mediapipe/camera_utils/camera_utils.js" crossorigin="anonymous"></script>
    <script src="https://cdn.jsdelivr.net/npm/@mediapipe/drawing_utils/drawing_utils.js" crossorigin="anonymous"></script>
    <script src="https://cdn.jsdelivr.net/npm/@mediapipe/hands/hands.js" crossorigin="anonymous"></script>
    <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>

    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@300;400;600;800&display=swap');
        body { font-family: 'Inter', sans-serif; }
        .font-mono { font-family: 'JetBrains Mono', monospace; }
        .mirrored { transform: scaleX(-1); }
        input[type=range] { -webkit-appearance: none; background: transparent; }
        input[type=range]::-webkit-slider-thumb {
            -webkit-appearance: none; height: 14px; width: 8px; border-radius: 2px;
            background: #ffffff; cursor: pointer; box-shadow: 0 0 5px rgba(255,255,255,0.5); margin-top: -6px;
        }
        input[type=range]::-webkit-slider-runnable-track {
            width: 100%; height: 2px; cursor: pointer; background: #27272a; border-radius: 1px;
        }
        .slider-cyan::-webkit-slider-thumb { background: #06b6d4; box-shadow: 0 0 8px rgba(6, 182, 212, 0.8); }
        .slider-rose::-webkit-slider-thumb { background: #f43f5e; box-shadow: 0 0 8px rgba(244, 63, 94, 0.8); }
        .glass-panel { background: rgba(24, 24, 27, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.05); }
        .custom-scrollbar::-webkit-scrollbar { width: 4px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: #27272a; border-radius: 2px; }
    </style>
</head>

<body class="bg-[#09090b] text-zinc-300 min-h-screen overflow-x-hidden selection:bg-cyan-500/30 selection:text-cyan-50 flex flex-col">
    <div class="max-w-[1400px] w-full mx-auto px-4 py-6 h-screen flex flex-col min-h-0">
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
                <div class="flex items-center gap-2">
                    <span class="text-[10px] text-zinc-500 font-mono uppercase tracking-widest">ESP32</span>
                    <div class="flex items-center gap-2 px-2 py-1 bg-zinc-900 border border-zinc-800 rounded">
                        <span id="status_dot" class="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse"></span>
                        <span id="esp32_status" class="text-[10px] font-mono text-zinc-400">WAITING</span>
                    </div>
                </div>

                <a href="/logout" class="text-[10px] font-mono text-zinc-500 hover:text-rose-400 uppercase tracking-widest">Logout</a>

                <button id="camToggle" onclick="toggleCamera()" class="group relative px-5 py-2 bg-zinc-900 hover:bg-cyan-950 border border-zinc-800 hover:border-cyan-500/50 transition-all rounded">
                    <span class="relative text-xs font-mono text-zinc-300 group-hover:text-cyan-400 tracking-widest uppercase flex items-center gap-2">
                        INIT CAMERA
                    </span>
                </button>
            </div>
        </header>

        <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 xl:gap-8 flex-grow min-h-0 overflow-hidden pb-4">
            <div class="lg:col-span-4 h-full flex flex-col min-h-0">
                <div class="glass-panel p-4 rounded-xl flex flex-col items-center h-full min-h-0">
                    <div class="flex w-full justify-between items-center mb-3 flex-shrink-0">
                        <h2 class="text-[10px] font-mono text-zinc-400 tracking-widest uppercase">Viewport.Feed</h2>
                        <span id="fps_counter" class="text-[10px] font-mono text-cyan-400 bg-cyan-400/10 px-1.5 py-0.5 rounded">0 FPS</span>
                    </div>

                    <div class="relative w-full flex-grow bg-zinc-950 rounded-lg overflow-hidden border border-zinc-800/80 min-h-0 flex items-center justify-center">
                        <video id="input_video" class="hidden" playsinline></video>
                        <canvas id="output_canvas" class="w-full h-full object-contain mirrored opacity-90"></canvas>
                        <div id="loadingAI" class="absolute inset-0 flex flex-col items-center justify-center bg-zinc-950/80 backdrop-blur-sm z-10 hidden">
                            <div class="animate-spin h-6 w-6 border-2 border-cyan-500 border-t-transparent rounded-full mb-4"></div>
                            <span class="text-cyan-400 font-mono tracking-widest text-[10px] uppercase">Booting VECTRA Core...</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="lg:col-span-3 h-full flex flex-col min-h-0">
                <div class="glass-panel p-4 rounded-xl flex flex-col h-full min-h-0">
                    <div class="flex w-full justify-between items-center mb-2 border-b border-zinc-800 pb-2 flex-shrink-0">
                        <h2 class="text-[10px] font-mono text-zinc-400 tracking-widest uppercase">Stream_Log</h2>
                        <button onclick="clearLog()" class="text-[9px] font-mono text-zinc-500 hover:text-cyan-400 transition-colors uppercase tracking-widest">Clear</button>
                    </div>
                    <div class="text-[10px] font-mono text-zinc-400 mb-2 pb-2 border-b border-zinc-800/50 leading-relaxed flex-shrink-0">
                        <span class="text-cyan-500/70 font-semibold tracking-wider">FORMAT:</span> [Jempol, Telunjuk, Tengah, Manis, Kelingking]<br>
                        <span class="text-zinc-600">Terbaru di urutan paling atas.</span>
                    </div>
                    <div id="terminal_log" class="flex-grow overflow-y-auto h-0 min-h-0 text-[11px] font-mono text-cyan-500/90 space-y-1.5 pr-2 custom-scrollbar">
                        <div class="text-zinc-600 italic mt-1">Standby. Menunggu data AI...</div>
                    </div>
                </div>
            </div>

            <div class="lg:col-span-5 h-full flex flex-col min-h-0">
                <div class="glass-panel p-6 rounded-xl flex flex-col justify-center h-full min-h-0 overflow-y-auto custom-scrollbar">
                    <div class="flex justify-between items-end mb-6 border-b border-zinc-800 pb-2 flex-shrink-0">
                        <h2 class="text-[10px] font-mono text-zinc-400 tracking-widest uppercase">Actuator.Calibration</h2>
                        <span class="text-[10px] font-mono text-zinc-600">PULSE WIDTH</span>
                    </div>

                    <div class="flex flex-col gap-3 flex-grow">
                        {% for name in jari_names %}
                        <div class="group relative px-4 py-3 rounded-lg bg-zinc-900/50 border border-zinc-800/50 hover:border-zinc-700 transition-colors">
                            <div class="flex flex-col xl:flex-row xl:items-center gap-4">
                                <span class="text-xs font-mono tracking-widest text-zinc-300 uppercase xl:w-20">{{ name }}</span>
                                <div class="flex-grow grid grid-cols-3 gap-4">
                                    <div>
                                        <div class="flex justify-between text-[10px] font-mono text-zinc-500 mb-1.5 uppercase">
                                            <span>MIN</span>
                                            <span class="text-cyan-400" id="{{name}}_min_txt">{{cal_data[name]['min']}}</span>
                                        </div>
                                        <input type="range" min="100" max="250" value="{{cal_data[name]['min']}}" class="w-full slider-cyan" oninput="updateCal('{{name}}', 'min', this.value)">
                                    </div>
                                    <div>
                                        <div class="flex justify-between text-[10px] font-mono text-zinc-500 mb-1.5 uppercase">
                                            <span>MAX</span>
                                            <span class="text-rose-400" id="{{name}}_max_txt">{{cal_data[name]['max']}}</span>
                                        </div>
                                        <input type="range" min="400" max="600" value="{{cal_data[name]['max']}}" class="w-full slider-rose" oninput="updateCal('{{name}}', 'max', this.value)">
                                    </div>
                                    <div class="flex flex-col justify-center">
                                        <div class="flex justify-between text-[10px] font-mono text-zinc-500 mb-1.5 uppercase">
                                            <span>REVERSE</span>
                                            <span class="text-amber-400" id="{{name}}_reverse_txt">{{ 'ON' if cal_data[name].get('reverse') else 'OFF' }}</span>
                                        </div>
                                        <label class="flex items-center gap-2 text-xs font-mono text-zinc-400 uppercase">
                                            <input id="{{name}}_reverse_cb" type="checkbox" {% if cal_data[name].get('reverse') %}checked{% endif %} onchange="updateCal('{{name}}', 'reverse', this.checked)" class="w-4 h-4 accent-amber-500"> Balik arah
                                        </label>
                                    </div>
                                </div>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                    <div class="mt-4 text-right flex-shrink-0">
                        <p class="text-[9px] font-mono text-zinc-600 uppercase">Data auto-save ke calibration.json</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

<script>
const socket = io({ transports: ["websocket", "polling"] });
let calData = {{ cal_data | tojson | safe }};
const jariNames = ["Jempol", "Telunjuk", "Tengah", "Manis", "Kelingking"];

let prevAngles = [0, 0, 0, 0, 0];
const ALPHA = 0.40;
let lastFrameTime = performance.now();
let frameCount = 0;
let lastEmit = 0;
const EMIT_INTERVAL_MS = 33;

const terminalLog = document.getElementById('terminal_log');
let logCount = 0;
const MAX_LOG_LINES = 25;

function addLog(pulses) {
    const now = new Date();
    const timeStr = now.getSeconds().toString().padStart(2, '0') + '.' + now.getMilliseconds().toString().padStart(3, '0');
    if (logCount === 0) terminalLog.innerHTML = '';
    const line = document.createElement('div');
    line.innerHTML = `<span class="text-zinc-600">[${timeStr}]</span> <span class="text-zinc-500">TX:</span> <span class="text-cyan-400">${pulses.join('<span class="text-zinc-700">,</span> ')}</span>`;
    terminalLog.prepend(line);
    logCount++;
    if (terminalLog.childElementCount > MAX_LOG_LINES) terminalLog.removeChild(terminalLog.lastChild);
}

function clearLog() {
    terminalLog.innerHTML = '<div class="text-zinc-600 italic mt-1">Standby. Menunggu data...</div>';
    logCount = 0;
}

function updateCal(jari, type, val) {
    let value = val;

    if (type === "reverse") {
        value = !!val;
        calData[jari][type] = value;
        document.getElementById(jari + "_reverse_txt").innerText = value ? "ON" : "OFF";
    } else {
        value = parseInt(val);
        document.getElementById(jari + "_" + type + "_txt").innerText = value;
        calData[jari][type] = value;
    }

    fetch('/update', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({jari: jari, type: type, value: value})
    });
}

function mapRange(value, in_min, in_max, out_min, out_max) {
    value = Math.max(Math.min(value, in_max), in_min);
    return ((value - in_min) * (out_max - out_min) / (in_max - in_min)) + out_min;
}

function getJointAngle4Points(p1, p2, p3, p4) {
    let v1 = {x: p2.x - p1.x, y: p2.y - p1.y, z: p2.z - p1.z};
    let v2 = {x: p4.x - p3.x, y: p4.y - p3.y, z: p4.z - p3.z};
    let dotProd = v1.x * v2.x + v1.y * v2.y + v1.z * v2.z;
    let mag1 = Math.sqrt(v1.x**2 + v1.y**2 + v1.z**2);
    let mag2 = Math.sqrt(v2.x**2 + v2.y**2 + v2.z**2);
    if (mag1 * mag2 === 0) return 0;
    let cosineAngle = Math.max(-1, Math.min(1, dotProd / (mag1 * mag2)));
    return (Math.acos(cosineAngle) * 180) / Math.PI;
}

const videoElement = document.getElementById('input_video');
const canvasElement = document.getElementById('output_canvas');
const canvasCtx = canvasElement.getContext('2d');
let cameraStarted = false;
let cameraObj = null;

function resizeCanvas() {
    const rect = canvasElement.getBoundingClientRect();
    canvasElement.width = Math.max(320, Math.floor(rect.width));
    canvasElement.height = Math.max(240, Math.floor(rect.height));
}
window.addEventListener('resize', resizeCanvas);

const hands = new Hands({locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`});
hands.setOptions({maxNumHands: 1, modelComplexity: 1, minDetectionConfidence: 0.7, minTrackingConfidence: 0.7});
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
        drawConnectors(canvasCtx, lm, HAND_CONNECTIONS, {color: 'rgba(6, 182, 212, 0.5)', lineWidth: 2});
        drawLandmarks(canvasCtx, lm, {color: '#22d3ee', lineWidth: 1, radius: 2});

        let rawAngles = [];
        let thumbBend1 = getJointAngle4Points(lm[1], lm[2], lm[2], lm[3]);
        let thumbBend2 = getJointAngle4Points(lm[2], lm[3], lm[3], lm[4]);
        rawAngles.push(mapRange(thumbBend1 + thumbBend2, 15, 90, 0, 180));

        const fingersData = [[5,6,7,8], [9,10,11,12], [13,14,15,16], [17,18,19,20]];
        for (let idx of fingersData) {
            let angle = getJointAngle4Points(lm[idx[0]], lm[idx[1]], lm[idx[2]], lm[idx[3]]);
            if (lm[idx[3]].y > lm[idx[1]].y && angle > 110) rawAngles.push(180);
            else rawAngles.push(mapRange(angle, 15, 145, 0, 180));
        }

        let pulsesToSend = [];
        for(let i = 0; i < 5; i++) {
            prevAngles[i] = (ALPHA * rawAngles[i]) + ((1 - ALPHA) * prevAngles[i]);
            let cMin = calData[jariNames[i]].min;
            let cMax = calData[jariNames[i]].max;
            let angleForServo = calData[jariNames[i]].reverse ? (180 - prevAngles[i]) : prevAngles[i];
            let pulse = cMin + (angleForServo * (cMax - cMin) / 180);
            pulsesToSend.push(Math.round(pulse));
        }

        if (now - lastEmit >= EMIT_INTERVAL_MS) {
            lastEmit = now;
            socket.emit('send_pulses', {pulses: pulsesToSend});
            addLog(pulsesToSend);
        }
    }
    canvasCtx.restore();
}

function toggleCamera() {
    const btn = document.getElementById('camToggle');
    const loading = document.getElementById('loadingAI');
    const spanText = btn.querySelector('span');

    if(!cameraStarted) {
        resizeCanvas();
        loading.classList.remove('hidden');
        spanText.innerText = "BOOTING...";

        const vidWidth = window.innerWidth < 640 ? 480 : 640;
        const vidHeight = window.innerWidth < 640 ? 640 : 480;

        cameraObj = new Camera(videoElement, {
            onFrame: async () => {
                await hands.send({image: videoElement});
                if(!loading.classList.contains('hidden')) {
                    loading.classList.add('hidden');
                    spanText.innerText = "HALT CAM";
                    spanText.className = "relative text-xs font-mono text-rose-400 group-hover:text-rose-300 tracking-widest uppercase flex items-center gap-2";
                }
            },
            width: vidWidth,
            height: vidHeight
        });
        cameraObj.start();
        cameraStarted = true;
    } else {
        if (cameraObj) cameraObj.stop();
        canvasCtx.clearRect(0, 0, canvasElement.width, canvasElement.height);
        spanText.innerText = "INIT CAMERA";
        spanText.className = "relative text-xs font-mono text-zinc-300 group-hover:text-cyan-400 tracking-widest uppercase flex items-center gap-2";
        cameraStarted = false;
        document.getElementById('fps_counter').innerText = "0 FPS";
        clearLog();
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
            txt.innerText = data.ip || "CONNECTED";
            txt.className = "text-[10px] font-mono text-cyan-400";
        } else {
            dot.className = "w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse";
            txt.innerText = "WAITING";
            txt.className = "text-[10px] font-mono text-zinc-500";
        }
    } catch(e) {}
}

setInterval(checkStatus, 2000);
checkStatus();
</script>
</body>
</html>
"""


# =====================================================
# FLASK ROUTES
# =====================================================
@app.route("/")
def index():
    if not is_logged_in():
        return redirect(url_for("login"))
    return render_template_string(HTML_TEMPLATE, jari_names=jari_names, cal_data=calibration_data)


@app.route("/update", methods=["POST"])
def update_data():
    global calibration_data

    if not is_logged_in():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    req = request.get_json(silent=True) or {}
    jari = req.get("jari")
    cal_type = req.get("type")
    value = req.get("value")

    if jari not in calibration_data or cal_type not in ["min", "max", "reverse"]:
        return jsonify({"status": "error", "message": "Invalid calibration key"}), 400

    if cal_type == "reverse":
        value = bool(value)
    else:
        try:
            value = int(value)
        except Exception:
            return jsonify({"status": "error", "message": "Invalid value"}), 400

    with lock:
        calibration_data[jari][cal_type] = value
        save_calibration(calibration_data)

    send_to_esp32({
        "type": "servo_config",
        "reverse": [bool(calibration_data[name].get("reverse", False)) for name in jari_names],
        "min": [int(calibration_data[name].get("min", 130)) for name in jari_names],
        "max": [int(calibration_data[name].get("max", 490)) for name in jari_names]
    })

    return jsonify({"status": "success"})


@app.route("/api/status", methods=["GET"])
def get_status():
    if not is_logged_in():
        return jsonify({"connected": False, "ip": "", "unauthorized": True}), 401

    with lock:
        connected = esp32_connected and esp32_ws is not None and (time.time() - esp32_last_seen) < 10
        ip = esp32_ip if connected else ""

    return jsonify({
        "connected": connected,
        "ip": ip,
        "last_seen": esp32_last_seen if connected else 0,
        "mode": "plain_websocket"
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


# =====================================================
# MAIN
# =====================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    local_ip = get_local_ip()
    
    print("\n" + "="*50)
    print("🚀 VECTRA LOCAL SERVER - QUICK START GUIDE")
    print("="*50)
    print(f"🌐 DASHBOARD BROWSER:")
    print(f"   http://localhost:{port}")
    print(f"   http://{local_ip}:{port} (Dari perangkat lain)")
    print(f"\n🤖 CONFIG ESP32 (Masukkan di halaman config ESP32):")
    print(f"   Domain/IP Server : {local_ip}")
    print(f"   Port             : {port}")
    print(f"   SSL/WSS          : OFF (Kosongkan/Uncheck)")
    print(f"\n🔑 PASSWORD DASHBOARD: {VECTRA_PASSWORD}")
    print("="*50 + "\n")
    
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True
    )
