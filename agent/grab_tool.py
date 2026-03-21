"""
grab_tool.py — cattura frame in RAM (/dev/shm). Gira sul Raspberry Pi.

Cattura con rpicam-still (CSI camera IMX219 su /dev/video0).
Nessun servizio esterno richiesto.

Non gira in daemon. Viene avviato dall'agente solo quando serve, poi esce.

Uso:
    python3 grab_tool.py immediate <session_id> <n_frames> <interval_ms> [width] [height] [quality]
    python3 grab_tool.py serial    <session_id> <port> <baud> <timeout_sec> [width] [height] [quality]

Storage: /dev/shm/grab_<session_id>/  ← RAM, NON la SD card

Output (stdout):
    Modalità serial: righe seriali non-VCAP passate in tempo reale
    Ultima riga (sempre presente):
        FRAMES:/dev/shm/grab_X/frame_000.jpg,...
        oppure FRAMES:  se nessun frame catturato

Protocollo VCAP (modalità serial, segnali ESP32 via Serial.println):
    VCAP_READY          → ack, nessuna azione
    VCAP_START <N> <T>  → cattura N frame ogni T ms
    VCAP_NOW [label]    → cattura un singolo frame
    VCAP_END            → esci subito
"""

import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime

# ── Configurazione ─────────────────────────────────────────────────────────────
SHM_BASE = "/dev/shm"


# ── Argomenti ─────────────────────────────────────────────────────────────────

def _usage():
    print(__doc__, file=sys.stderr)
    sys.exit(1)

if len(sys.argv) < 2:
    _usage()

MODE = sys.argv[1]

if MODE == "immediate":
    if len(sys.argv) < 5:
        _usage()
    SESSION_ID  = sys.argv[2]
    N_FRAMES    = int(sys.argv[3])
    INTERVAL_MS = int(sys.argv[4])
    WIDTH       = int(sys.argv[5]) if len(sys.argv) > 5 else 640
    HEIGHT      = int(sys.argv[6]) if len(sys.argv) > 6 else 480
    QUALITY     = int(sys.argv[7]) if len(sys.argv) > 7 else 75
    PORT = BAUD = TIMEOUT = None

elif MODE == "serial":
    if len(sys.argv) < 7:
        _usage()
    SESSION_ID  = sys.argv[2]
    PORT        = sys.argv[3]
    BAUD        = int(sys.argv[4])
    TIMEOUT     = int(sys.argv[5])
    WIDTH       = int(sys.argv[6]) if len(sys.argv) > 6 else 640
    HEIGHT      = int(sys.argv[7]) if len(sys.argv) > 7 else 480
    QUALITY     = int(sys.argv[8]) if len(sys.argv) > 8 else 75
    N_FRAMES = INTERVAL_MS = None

else:
    _usage()


# ── Setup storage in RAM ───────────────────────────────────────────────────────

OUTPUT_DIR = os.path.join(SHM_BASE, f"grab_{SESSION_ID}")
os.makedirs(OUTPUT_DIR, exist_ok=True)

captured_frames = []
_capture_lock   = threading.Lock()
_done_event     = threading.Event()
_frame_counter  = 0
_counter_lock   = threading.Lock()


def _log(msg: str):
    print(f"[grab] {msg}", file=sys.stderr, flush=True)


def _next_path(label: str = "") -> str:
    global _frame_counter
    with _counter_lock:
        idx = _frame_counter
        _frame_counter += 1
    ts = datetime.utcnow().strftime("%H%M%S_%f")[:12]
    safe = re.sub(r"[^\w]", "_", label)[:20] if label else ""
    name = f"frame_{idx:03d}_{ts}" + (f"_{safe}" if safe else "") + ".jpg"
    return os.path.join(OUTPUT_DIR, name)


# ── Cattura ────────────────────────────────────────────────────────────────────

def _capture_one(label: str = "") -> str | None:
    """
    Cattura un singolo frame con rpicam-still.
    Ritorna il path del file o None se fallisce.

    Parametri ottimizzati per display OLED su sfondo scuro:
    - AWB disabilitato, guadagni manuali neutrali per luce artificiale
    - Contrasto aumentato per far emergere i pixel bianchi OLED
    - Esposizione leggermente ridotta per non saturare l'OLED
    - Sharpness aumentata per dettagli pixel
    """
    path = _next_path(label)
    cmd = [
        "rpicam-still",
        "-o", path,
        "--nopreview",
        "--immediate",
        "-t", "300",
        "--width",  str(WIDTH),
        "--height", str(HEIGHT),
        "-q", str(QUALITY),
        # Bilanciamento bianco manuale: neutrali per luce LED/artificiale
        "--awbgains", "2.0,1.6",
        # Contrasto: rende pixel OLED bianchi più netti sul nero
        "--contrast", "1.8",
        # Sharpness: migliora la definizione dei bordi pixel
        "--sharpness", "2.0",
        # EV molto negativo: isola pixel OLED dal rumore (ottimale anche al buio)
        # Calibrato con occhio_bionico.calibrate() — preset 'bright' vince (density 8.9% vs 2.5%)
        "--ev", "-1.5",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=10)
        if r.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 500:
            size_kb = os.path.getsize(path) // 1024
            _log(f"frame catturato: {os.path.basename(path)} ({size_kb}KB)")
            with _capture_lock:
                captured_frames.append(path)
            return path
        else:
            _log(f"rpicam-still fallito (rc={r.returncode}) per {os.path.basename(path)}")
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        _log(f"errore cattura: {e}")
        return None


def _capture_sequence(n: int, interval_ms: int):
    """Cattura N frame con pausa interval_ms ms tra ciascuno (in thread separato)."""
    _log(f"sequenza: {n} frame ogni {interval_ms}ms")
    for i in range(n):
        if _done_event.is_set():
            break
        _capture_one(f"s{i}")
        if i < n - 1:
            time.sleep(interval_ms / 1000.0)
    _log("sequenza completata")


def _emit_result():
    """Stampa la riga FRAMES: su stdout ed esce."""
    _done_event.set()
    with _capture_lock:
        frames = list(captured_frames)
    print(f"FRAMES:{','.join(frames)}", flush=True)
    _log(f"totale frame catturati: {len(frames)}")


# ══════════════════════════════════════════════════════════════════════════════
# MODALITÀ IMMEDIATE
# ══════════════════════════════════════════════════════════════════════════════

if MODE == "immediate":
    _log(f"immediate: {N_FRAMES} frame ogni {INTERVAL_MS}ms → {OUTPUT_DIR}")
    _capture_sequence(N_FRAMES, INTERVAL_MS)
    _emit_result()
    sys.exit(0)


# ══════════════════════════════════════════════════════════════════════════════
# MODALITÀ SERIAL — ascolta VCAP da ESP32 via porta seriale
# La lettura è bloccante (I/O wait), CPU ≈ 0% mentre si aspetta
# Esce immediatamente su VCAP_END o allo scadere del timeout
# ══════════════════════════════════════════════════════════════════════════════

try:
    import serial as _serial
except ImportError:
    _log("pyserial non installato")
    _emit_result()
    sys.exit(2)

_log(f"serial: {PORT} @ {BAUD} baud, timeout={TIMEOUT}s → {OUTPUT_DIR}")

try:
    ser = _serial.Serial(PORT, BAUD, timeout=1)
except _serial.SerialException as e:
    _log(f"impossibile aprire {PORT}: {e}")
    _emit_result()
    sys.exit(3)

capture_thread = None
deadline = time.time() + TIMEOUT

try:
    while time.time() < deadline:
        # readline() con timeout=1 → bloccante, CPU ≈ 0% in attesa
        try:
            raw = ser.readline()
        except _serial.SerialException as e:
            _log(f"errore lettura seriale: {e}")
            break

        if not raw:
            continue

        line = raw.replace(b'\x00', b'').decode(errors="replace").rstrip("\r\n")
        if not line:
            continue

        # ── Segnali VCAP ──────────────────────────────────────────────────────
        if line.startswith("VCAP_"):
            _log(f"VCAP: {line}")

            if line == "VCAP_READY":
                pass

            elif line.startswith("VCAP_START"):
                parts = line.split()
                n = int(parts[1]) if len(parts) > 1 else 1
                t = int(parts[2]) if len(parts) > 2 else 1000
                if capture_thread and capture_thread.is_alive():
                    _log("thread precedente ancora attivo, skip")
                else:
                    capture_thread = threading.Thread(
                        target=_capture_sequence, args=(n, t), daemon=True
                    )
                    capture_thread.start()

            elif line.startswith("VCAP_NOW"):
                parts = line.split(maxsplit=1)
                label = parts[1] if len(parts) > 1 else ""
                threading.Thread(target=_capture_one, args=(label,), daemon=True).start()

            elif line == "VCAP_END":
                _log("VCAP_END → esco")
                break

            continue  # segnali VCAP non vanno sull'output normale

        # Riga seriale normale → stdout (raccolta da collect_grab)
        print(line, flush=True)

except KeyboardInterrupt:
    _log("interrotto (SIGINT)")
finally:
    ser.close()

_done_event.set()
if capture_thread and capture_thread.is_alive():
    _log("attendo fine thread cattura...")
    capture_thread.join(timeout=15)

_emit_result()
