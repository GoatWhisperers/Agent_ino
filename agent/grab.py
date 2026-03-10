"""
grab.py — tool di cattura frame per l'agente Arduino.

Due tool disponibili per il modello (MI50):

  grab_now(n_frames, interval_ms, resolution, quality)
      Cattura immediata dal Raspberry Pi senza ESP32.
      Utile per: debug camera, analisi stato fisico statico, test.
      Ritorna: list[str] con i path locali dei frame (su /tmp server).

  start_serial_grab(port, baud, timeout_sec, width, height, quality)
      Avvia grab_tool in background sul Raspberry in modalità serial.
      L'ESP32 comanda il timing via VCAP (Serial.println("VCAP_START N T")).
      Ritorna: session_id (str) da passare a collect_grab().

  collect_grab(session_id)
      Aspetta fine sessione, SCP frame /dev/shm→server, ritorna dict.

  cleanup_grab(session_id)
      Rimuove /dev/shm/grab_<session> sul Raspberry e /tmp locale.

  deploy()
      SCP grab_tool.py sul Raspberry (solo se modificato).

Storage Raspberry: /dev/shm/grab_<session>/   ← RAM, NON la SD card
Storage server:    /tmp/grab_local_<session>/  ← temporaneo, rimosso da cleanup
"""

import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path

# ── Configurazione ─────────────────────────────────────────────────────────────
RPI_HOST     = "192.168.1.167"
RPI_USER     = "lele"
RPI_PASSWORD = "pippopippo33$$"
RPI_SERIAL   = "/dev/ttyUSB0"

_TOOL_LOCAL  = Path(__file__).parent / "grab_tool.py"
_TOOL_REMOTE = "~/grab_tool.py"
_RPI_SHM     = "/dev/shm"
_LOCAL_TMP   = "/tmp"


# ── Utility SSH/SCP ────────────────────────────────────────────────────────────

def _pfx() -> list[str]:
    return ["sshpass", "-p", RPI_PASSWORD]


def _ssh(cmd: str, timeout: int = 60) -> dict:
    full = _pfx() + ["ssh", "-o", "StrictHostKeyChecking=no",
                      "-o", "ConnectTimeout=10",
                      f"{RPI_USER}@{RPI_HOST}", cmd]
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        return {"rc": r.returncode, "out": r.stdout, "err": r.stderr}
    except subprocess.TimeoutExpired:
        return {"rc": -1, "out": "", "err": f"SSH timeout ({timeout}s)"}
    except FileNotFoundError:
        return {"rc": -1, "out": "", "err": "sshpass non trovato"}


def _ssh_bg(cmd: str, stdout_file: str) -> dict:
    """Lancia un comando SSH in background (nohup), stdout in file remoto."""
    bg = f"nohup bash -c '{cmd}' > {stdout_file} 2>/dev/null </dev/null &"
    return _ssh(bg, timeout=10)


def _scp_to(local: str, remote: str, timeout: int = 30) -> dict:
    full = _pfx() + ["scp", "-o", "StrictHostKeyChecking=no",
                      local, f"{RPI_USER}@{RPI_HOST}:{remote}"]
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        return {"ok": r.returncode == 0, "err": (r.stderr or r.stdout).strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "err": f"SCP timeout ({timeout}s)"}
    except FileNotFoundError:
        return {"ok": False, "err": "sshpass non trovato"}


def _scp_from(remote: str, local: str, timeout: int = 60) -> dict:
    """SCP ricorsivo Raspberry → server."""
    full = _pfx() + ["scp", "-r", "-o", "StrictHostKeyChecking=no",
                      f"{RPI_USER}@{RPI_HOST}:{remote}", local]
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        return {"ok": r.returncode == 0, "err": (r.stderr or r.stdout).strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "err": f"SCP timeout ({timeout}s)"}
    except FileNotFoundError:
        return {"ok": False, "err": "sshpass non trovato"}


# ── Deploy ─────────────────────────────────────────────────────────────────────

def deploy() -> dict:
    """
    SCP grab_tool.py sul Raspberry. Skip se già identico (confronto MD5).
    Ritorna {"ok": bool, "deployed": bool, "error": str|None}
    """
    if not _TOOL_LOCAL.exists():
        return {"ok": False, "deployed": False, "error": f"grab_tool.py non trovato: {_TOOL_LOCAL}"}

    local_md5 = hashlib.md5(_TOOL_LOCAL.read_bytes()).hexdigest()
    r = _ssh(f"md5sum {_TOOL_REMOTE} 2>/dev/null | awk '{{print $1}}'", timeout=10)
    remote_md5 = r["out"].strip()

    if remote_md5 == local_md5:
        return {"ok": True, "deployed": False, "error": None}

    r = _scp_to(str(_TOOL_LOCAL), _TOOL_REMOTE)
    if not r["ok"]:
        return {"ok": False, "deployed": False, "error": f"SCP fallito: {r['err']}"}

    return {"ok": True, "deployed": True, "error": None}


# ── Tool 1: grab_now ───────────────────────────────────────────────────────────

def grab_now(
    n_frames: int     = 3,
    interval_ms: int  = 500,
    width: int        = 640,
    height: int       = 480,
    quality: int      = 75,
    timeout: int      = 60,
) -> dict:
    """
    TOOL PER IL MODELLO — Cattura immediata, nessun ESP32 necessario.

    Parametri:
        n_frames    : numero frame da catturare (consigliato: 1-10)
        interval_ms : ms tra un frame e il successivo (consigliato: 200-2000)
        width       : larghezza in pixel (default 640)
        height      : altezza in pixel (default 480)
        quality     : qualità JPEG 0-100 (default 75)
        timeout     : timeout SSH in secondi

    Ritorna:
        {
            "ok":          bool,
            "frame_paths": list[str],   # path locali sul server (in /tmp)
            "n_frames":    int,
            "error":       str | None,
        }
    """
    # Deploy tool se necessario
    dep = deploy()
    if not dep["ok"]:
        return {"ok": False, "frame_paths": [], "n_frames": 0, "error": dep["error"]}

    session_id = f"now_{int(time.time() * 1000)}"
    remote_dir = f"{_RPI_SHM}/grab_{session_id}"
    stdout_remote = f"{_RPI_SHM}/grab_{session_id}_out.txt"

    cmd = (
        f"python3 {_TOOL_REMOTE} immediate {session_id} "
        f"{n_frames} {interval_ms} {width} {height} {quality}"
    )

    # Esegui in foreground (attende completamento)
    r = _ssh(cmd, timeout=timeout)
    raw_out = r["out"]

    # Analizza output: ultima riga = FRAMES:...
    frame_paths_remote = []
    for line in raw_out.splitlines():
        if line.startswith("FRAMES:"):
            paths = line[len("FRAMES:"):].strip()
            if paths:
                frame_paths_remote = [p for p in paths.split(",") if p.strip()]

    if not frame_paths_remote:
        err = r["err"].strip()[-300:] if r["err"] else "Nessun frame catturato"
        return {"ok": False, "frame_paths": [], "n_frames": 0, "error": err}

    # SCP frame → server
    local_dir = f"{_LOCAL_TMP}/grab_local_{session_id}"
    os.makedirs(local_dir, exist_ok=True)
    scp = _scp_from(remote_dir, local_dir, timeout=60)
    if not scp["ok"]:
        return {"ok": False, "frame_paths": [], "n_frames": 0,
                "error": f"SCP frame fallito: {scp['err']}"}

    # Mappa path remoti → path locali
    local_frames = []
    for rp in frame_paths_remote:
        fname = os.path.basename(rp)
        lp = os.path.join(local_dir, os.path.basename(remote_dir), fname)
        if not os.path.exists(lp):
            # Fallback: cerca nella dir scaricata
            lp = os.path.join(local_dir, fname)
        if os.path.exists(lp):
            local_frames.append(lp)

    # Cleanup remoto
    _ssh(f"rm -rf {remote_dir} {stdout_remote} 2>/dev/null", timeout=10)

    return {
        "ok": True,
        "frame_paths": local_frames,
        "n_frames": len(local_frames),
        "error": None,
    }


# ── Tool 2a: start_serial_grab ─────────────────────────────────────────────────

def start_serial_grab(
    port: str        = RPI_SERIAL,
    baud: int        = 115200,
    timeout_sec: int = 30,
    width: int       = 640,
    height: int      = 480,
    quality: int     = 75,
) -> str:
    """
    TOOL PER IL MODELLO — Avvia listener VCAP in background sul Raspberry.
    L'ESP32 comanda il timing via Serial.println("VCAP_START N T").

    Parametri:
        port        : porta seriale ESP32 sul Raspberry (default /dev/ttyUSB0)
        baud        : baud rate (default 115200)
        timeout_sec : timeout massimo in secondi (default 30)
        width/height: risoluzione frame
        quality     : qualità JPEG

    Ritorna:
        session_id (str) da passare a collect_grab() dopo l'upload del firmware.
    """
    dep = deploy()
    if not dep["ok"]:
        raise RuntimeError(f"deploy grab_tool fallito: {dep['error']}")

    session_id   = f"ser_{int(time.time() * 1000)}"
    stdout_remote = f"{_RPI_SHM}/grab_{session_id}_out.txt"

    cmd = (
        f"python3 {_TOOL_REMOTE} serial {session_id} "
        f"{port} {baud} {timeout_sec} {width} {height} {quality}"
    )
    _ssh_bg(cmd, stdout_remote)
    return session_id


# ── Tool 2b: collect_grab ──────────────────────────────────────────────────────

def collect_grab(
    session_id: str,
    wait_timeout: int = 60,
) -> dict:
    """
    Aspetta che la sessione VCAP termini, SCP frame → server.

    Ritorna:
        {
            "ok":           bool,
            "frame_paths":  list[str],   # path locali sul server
            "serial_output": str,        # righe seriali non-VCAP
            "lines":        list[str],
            "n_frames":     int,
            "error":        str | None,
        }
    """
    stdout_remote = f"{_RPI_SHM}/grab_{session_id}_out.txt"
    remote_dir    = f"{_RPI_SHM}/grab_{session_id}"

    # Aspetta che grab_tool.py termini (poll su processo)
    deadline = time.time() + wait_timeout
    while time.time() < deadline:
        r = _ssh("pgrep -f grab_tool.py 2>/dev/null | wc -l", timeout=10)
        if r["out"].strip() == "0":
            break
        time.sleep(2)

    # Leggi stdout remoto
    r = _ssh(f"cat {stdout_remote} 2>/dev/null", timeout=15)
    raw = r["out"]

    # Separa FRAMES: dal resto (serial output)
    serial_lines = []
    frame_paths_remote = []
    for line in raw.splitlines():
        line = line.rstrip("\r")
        if line.startswith("FRAMES:"):
            paths = line[len("FRAMES:"):].strip()
            if paths:
                frame_paths_remote = [p for p in paths.split(",") if p.strip()]
        elif line:
            serial_lines.append(line)

    serial_output = "\n".join(serial_lines)

    # SCP frame → server
    local_dir = f"{_LOCAL_TMP}/grab_local_{session_id}"
    os.makedirs(local_dir, exist_ok=True)

    local_frames = []
    if frame_paths_remote:
        scp = _scp_from(remote_dir, local_dir, timeout=60)
        if scp["ok"]:
            for rp in frame_paths_remote:
                fname = os.path.basename(rp)
                lp = os.path.join(local_dir, os.path.basename(remote_dir), fname)
                if not os.path.exists(lp):
                    lp = os.path.join(local_dir, fname)
                if os.path.exists(lp):
                    local_frames.append(lp)
        else:
            return {
                "ok": False,
                "frame_paths": [],
                "serial_output": serial_output,
                "lines": serial_lines,
                "n_frames": 0,
                "error": f"SCP frame fallito: {scp['err']}",
            }

    return {
        "ok": True,
        "frame_paths": local_frames,
        "serial_output": serial_output,
        "lines": serial_lines,
        "n_frames": len(local_frames),
        "error": None,
    }


# ── Cleanup ────────────────────────────────────────────────────────────────────

def cleanup_grab(session_id: str) -> None:
    """Rimuove /dev/shm/grab_<session> sul Raspberry e /tmp locale."""
    remote_dir    = f"{_RPI_SHM}/grab_{session_id}"
    stdout_remote = f"{_RPI_SHM}/grab_{session_id}_out.txt"
    _ssh(f"rm -rf {remote_dir} {stdout_remote} 2>/dev/null", timeout=10)

    local_dir = f"{_LOCAL_TMP}/grab_local_{session_id}"
    if os.path.isdir(local_dir):
        shutil.rmtree(local_dir, ignore_errors=True)


# ── CLI per test rapido ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        n  = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        ms = int(sys.argv[3]) if len(sys.argv) > 3 else 500
        print(f"Test grab_now: {n} frame ogni {ms}ms...")
        result = grab_now(n_frames=n, interval_ms=ms)
        if result["ok"]:
            print(f"OK: {result['n_frames']} frame catturati")
            for p in result["frame_paths"]:
                size = os.path.getsize(p) // 1024
                print(f"  {p}  ({size} KB)")
        else:
            print(f"ERRORE: {result['error']}")
    else:
        print("Uso: python grab.py test [n_frames] [interval_ms]")
