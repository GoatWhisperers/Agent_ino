"""
capture_frames.py — script da eseguire sul Raspberry Pi via SSH.

Legge la porta seriale, intercetta segnali VCAP_* e cattura frame con rpicam-still.

Uso:
    python3 capture_frames.py <port> <baud> <timeout_sec> <output_dir>

Protocollo VCAP (dal ESP32 via Serial.println):
    VCAP_READY           — ESP32 pronto
    VCAP_START <N> <T>   — cattura N frame ogni T ms
    VCAP_NOW <label>     — cattura singolo frame su evento
    VCAP_END             — fine, script può uscire prima del timeout

Output:
    - stdout: righe seriali normali (non-VCAP) + riga finale "FRAMES:/tmp/vcap/frame_000.jpg,..."
    - stderr: log operativi (non catturato dall'agente)
"""

import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime

# ── Argomenti ──────────────────────────────────────────────────────────────────

if len(sys.argv) < 5:
    print("Uso: python3 capture_frames.py <port> <baud> <timeout_sec> <output_dir>",
          file=sys.stderr)
    sys.exit(1)

PORT       = sys.argv[1]
BAUD       = int(sys.argv[2])
TIMEOUT    = int(sys.argv[3])
OUTPUT_DIR = sys.argv[4]

# ── Setup ──────────────────────────────────────────────────────────────────────

os.makedirs(OUTPUT_DIR, exist_ok=True)

captured_frames = []
_capture_lock   = threading.Lock()
_done_event     = threading.Event()

frame_counter = 0
_counter_lock = threading.Lock()


def _log(msg: str):
    print(f"[vcap] {msg}", file=sys.stderr, flush=True)


def _next_frame_path(label: str = "") -> str:
    global frame_counter
    with _counter_lock:
        idx = frame_counter
        frame_counter += 1
    ts = datetime.utcnow().strftime("%H%M%S_%f")[:12]
    safe_label = re.sub(r"[^\w]", "_", label)[:20] if label else ""
    name = f"frame_{idx:03d}_{ts}"
    if safe_label:
        name += f"_{safe_label}"
    name += ".jpg"
    return os.path.join(OUTPUT_DIR, name)


def _capture_one(label: str = "") -> str | None:
    """Cattura un singolo frame con rpicam-still. Ritorna il path o None."""
    path = _next_frame_path(label)
    cmd = [
        "rpicam-still",
        "-o", path,
        "--nopreview",
        "--immediate",
        "-t", "500",
        "--width", "640",
        "--height", "480",
        "-q", "75",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=10)
        if r.returncode == 0 and os.path.exists(path):
            _log(f"Frame catturato: {path}")
            with _capture_lock:
                captured_frames.append(path)
            return path
        else:
            _log(f"rpicam-still fallito (rc={r.returncode}): {r.stderr.decode(errors='replace')}")
            return None
    except subprocess.TimeoutExpired:
        _log("rpicam-still timeout")
        return None
    except FileNotFoundError:
        _log("rpicam-still non trovato")
        return None


def _capture_sequence(n: int, interval_ms: int):
    """Cattura N frame con intervallo interval_ms ms (eseguito in thread)."""
    _log(f"Inizio sequenza: {n} frame ogni {interval_ms}ms")
    for i in range(n):
        if _done_event.is_set():
            break
        _capture_one(f"seq{i}")
        if i < n - 1:
            time.sleep(interval_ms / 1000.0)
    _log("Sequenza completata")


# ── Lettura seriale ────────────────────────────────────────────────────────────

try:
    import serial
except ImportError:
    _log("pyserial non installato: pip install pyserial")
    sys.exit(2)

_log(f"Apertura {PORT} @ {BAUD} baud, timeout={TIMEOUT}s, output={OUTPUT_DIR}")

normal_lines = []
capture_thread = None

try:
    ser = serial.Serial(PORT, BAUD, timeout=1)
except serial.SerialException as e:
    _log(f"Impossibile aprire porta seriale: {e}")
    sys.exit(3)

deadline = time.time() + TIMEOUT

try:
    while time.time() < deadline:
        try:
            raw = ser.readline()
        except serial.SerialException as e:
            _log(f"Errore lettura seriale: {e}")
            break

        if not raw:
            continue

        line = raw.decode(errors="replace").rstrip("\r\n")

        # ── Interpreta segnali VCAP ────────────────────────────────────────────
        if line.startswith("VCAP_"):
            _log(f"Segnale ricevuto: {line}")

            if line == "VCAP_READY":
                _log("ESP32 pronto")

            elif line.startswith("VCAP_START"):
                # VCAP_START <N> <T>
                parts = line.split()
                n_frames = int(parts[1]) if len(parts) > 1 else 1
                interval  = int(parts[2]) if len(parts) > 2 else 1000
                if capture_thread and capture_thread.is_alive():
                    _log("Thread di cattura precedente ancora in esecuzione, skip")
                else:
                    capture_thread = threading.Thread(
                        target=_capture_sequence,
                        args=(n_frames, interval),
                        daemon=True,
                    )
                    capture_thread.start()

            elif line.startswith("VCAP_NOW"):
                # VCAP_NOW <label>
                parts = line.split(maxsplit=1)
                label = parts[1] if len(parts) > 1 else ""
                t = threading.Thread(target=_capture_one, args=(label,), daemon=True)
                t.start()

            elif line == "VCAP_END":
                _log("VCAP_END ricevuto, esco")
                _done_event.set()
                break

            # I segnali VCAP non vanno sull'output normale
            continue

        # Riga seriale normale
        print(line, flush=True)
        normal_lines.append(line)

except KeyboardInterrupt:
    _log("Interrotto (SIGINT)")
finally:
    ser.close()

# Aspetta thread di cattura in corso
_done_event.set()
if capture_thread and capture_thread.is_alive():
    _log("Attendo fine thread di cattura...")
    capture_thread.join(timeout=15)

# ── Output finale ──────────────────────────────────────────────────────────────

with _capture_lock:
    frames_copy = list(captured_frames)

if frames_copy:
    print(f"FRAMES:{','.join(frames_copy)}", flush=True)
else:
    print("FRAMES:", flush=True)

_log(f"Fine. {len(frames_copy)} frame catturati, {len(normal_lines)} righe seriali normali.")
