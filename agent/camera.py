"""
Camera — gestisce cattura frame su Raspberry Pi e trasferimento al server.

Flusso:
  1. deploy_capture_script() — SCP di capture_frames.py sul Raspberry (solo se cambiato)
  2. start_capture_session()  — avvia capture_frames.py in background SSH
  3. collect_frames()         — aspetta fine, SCP frames → server, ritorna dict
  4. cleanup_session()        — rimuove temp su Raspberry e server

Usa sshpass come in remote_uploader.py.
"""

import hashlib
import os
import subprocess
import tempfile
import time
from pathlib import Path

# ── Configurazione Raspberry Pi ───────────────────────────────────────────────
RPI_HOST     = "192.168.1.167"
RPI_USER     = "lele"
RPI_PASSWORD = "pippopippo33$$"

# Path locale dello script da deployare
_SCRIPT_LOCAL = Path(__file__).parent / "capture_frames.py"
# Path remoto sul Raspberry
_SCRIPT_REMOTE = "~/capture_frames.py"

# Directory temporanee
_RPI_TMP_BASE    = "/tmp"
_LOCAL_TMP_BASE  = "/tmp"


# ── Utility SSH/SCP (stesso pattern di remote_uploader.py) ───────────────────

def _sshpass_prefix() -> list:
    return ["sshpass", "-p", RPI_PASSWORD]


def _ssh(cmd: str, timeout: int = 60) -> dict:
    full_cmd = _sshpass_prefix() + [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{RPI_USER}@{RPI_HOST}",
        cmd,
    ]
    try:
        r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": f"SSH timeout ({timeout}s)"}
    except FileNotFoundError:
        return {"returncode": -1, "stdout": "", "stderr": "sshpass non trovato"}


def _ssh_background(cmd: str, timeout: int = 10) -> dict:
    """Lancia un comando SSH in background (nohup) sul Raspberry."""
    bg_cmd = f"nohup {cmd} </dev/null >/tmp/vcap_bg_stdout.txt 2>/tmp/vcap_bg_stderr.txt &"
    return _ssh(bg_cmd, timeout=timeout)


def _scp_to_rpi(local_path: str, remote_path: str, timeout: int = 30) -> dict:
    full_cmd = _sshpass_prefix() + [
        "scp", "-o", "StrictHostKeyChecking=no",
        local_path,
        f"{RPI_USER}@{RPI_HOST}:{remote_path}",
    ]
    try:
        r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        return {"success": r.returncode == 0, "error": (r.stderr or r.stdout).strip()}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"SCP timeout ({timeout}s)"}
    except FileNotFoundError:
        return {"success": False, "error": "sshpass/scp non trovato"}


def _scp_from_rpi(remote_path: str, local_path: str, timeout: int = 60) -> dict:
    """SCP ricorsivo dal Raspberry al server."""
    full_cmd = _sshpass_prefix() + [
        "scp", "-r", "-o", "StrictHostKeyChecking=no",
        f"{RPI_USER}@{RPI_HOST}:{remote_path}",
        local_path,
    ]
    try:
        r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        return {"success": r.returncode == 0, "error": (r.stderr or r.stdout).strip()}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"SCP timeout ({timeout}s)"}
    except FileNotFoundError:
        return {"success": False, "error": "sshpass/scp non trovato"}


# ── Funzioni pubbliche ────────────────────────────────────────────────────────

def deploy_capture_script() -> dict:
    """
    SCP di capture_frames.py sul Raspberry in ~/capture_frames.py.
    Evita il trasferimento se il file remoto è identico (confronto md5).

    Ritorna {"success": bool, "deployed": bool, "error": str|None}
    """
    if not _SCRIPT_LOCAL.exists():
        return {"success": False, "deployed": False,
                "error": f"Script locale non trovato: {_SCRIPT_LOCAL}"}

    local_md5 = hashlib.md5(_SCRIPT_LOCAL.read_bytes()).hexdigest()

    # Controlla hash remoto
    r = _ssh(f"md5sum {_SCRIPT_REMOTE} 2>/dev/null | awk '{{print $1}}'", timeout=15)
    remote_md5 = r["stdout"].strip()

    if remote_md5 == local_md5:
        return {"success": True, "deployed": False, "error": None}

    # File assente o diverso: copia
    r = _scp_to_rpi(str(_SCRIPT_LOCAL), _SCRIPT_REMOTE)
    if not r["success"]:
        return {"success": False, "deployed": False,
                "error": f"SCP script fallito: {r['error']}"}

    return {"success": True, "deployed": True, "error": None}


def start_capture_session(
    port: str = "/dev/ttyUSB0",
    baud: int = 115200,
    timeout_sec: int = 30,
    n_frames_hint: int = 5,
) -> str:
    """
    Avvia capture_frames.py in background SSH sul Raspberry.

    Ritorna session_id (stringa timestamp) che identifica la sessione.
    """
    session_id = str(int(time.time() * 1000))
    remote_dir = f"{_RPI_TMP_BASE}/vcap_{session_id}"

    # Crea dir remota
    _ssh(f"mkdir -p {remote_dir}", timeout=10)

    # Output del processo in remoto: stdout in file dedicato
    stdout_file = f"{_RPI_TMP_BASE}/vcap_{session_id}_out.txt"
    cmd = (
        f"python3 ~/capture_frames.py {port} {baud} {timeout_sec} {remote_dir} "
        f"> {stdout_file} 2>/tmp/vcap_{session_id}_err.txt"
    )

    # Lancia in background
    bg_full = (
        f"nohup bash -c '{cmd}' </dev/null "
        f">/tmp/vcap_{session_id}_launch.txt 2>&1 &"
    )
    _ssh(bg_full, timeout=10)

    return session_id


def collect_frames(
    session_id: str,
    serial_timeout: int = 30,
) -> dict:
    """
    Aspetta la fine della sessione di cattura, poi:
      1. Scarica stdout del processo (righe seriali + FRAMES:...)
      2. SCP dei frame dal Raspberry al server
      3. Ritorna dict con serial_output, lines, frame_paths, error

    Ritorna:
        {
            "serial_output": str,
            "lines": list[str],
            "frame_paths": list[str],   # path locali sul server
            "error": str | None,
        }
    """
    stdout_file = f"{_RPI_TMP_BASE}/vcap_{session_id}_out.txt"
    remote_dir  = f"{_RPI_TMP_BASE}/vcap_{session_id}"

    # Aspetta che il processo termini (poll su stdout con deadline)
    deadline = time.time() + serial_timeout + 10
    while time.time() < deadline:
        # Controlla se il processo capture_frames è ancora attivo
        r = _ssh(f"pgrep -f 'capture_frames.py' 2>/dev/null | wc -l", timeout=10)
        n_procs = int(r["stdout"].strip() or "0")
        if n_procs == 0:
            break
        time.sleep(2)

    # Leggi stdout remoto
    r = _ssh(f"cat {stdout_file} 2>/dev/null", timeout=15)
    raw_stdout = r["stdout"]

    # Separa la riga FRAMES: dal resto
    serial_lines = []
    frame_paths_remote = []

    for line in raw_stdout.splitlines():
        line_stripped = line.rstrip("\r")
        if line_stripped.startswith("FRAMES:"):
            # FRAMES:path1,path2,...
            paths_part = line_stripped[len("FRAMES:"):].strip()
            if paths_part:
                frame_paths_remote = [p for p in paths_part.split(",") if p.strip()]
        else:
            if line_stripped:
                serial_lines.append(line_stripped)

    serial_output = "\n".join(serial_lines)

    # Scarica frame localmente
    local_dir = f"{_LOCAL_TMP_BASE}/vcap_local_{session_id}"
    os.makedirs(local_dir, exist_ok=True)

    local_frame_paths = []

    if frame_paths_remote:
        # SCP l'intera directory remota
        r = _scp_from_rpi(f"{remote_dir}/", local_dir, timeout=60)
        if r["success"]:
            # Trova i file scaricati corrispondenti ai frame remoti
            for remote_fp in frame_paths_remote:
                fname = os.path.basename(remote_fp)
                local_fp = os.path.join(local_dir, fname)
                if os.path.exists(local_fp):
                    local_frame_paths.append(local_fp)
        else:
            return {
                "serial_output": serial_output,
                "lines": serial_lines,
                "frame_paths": [],
                "error": f"SCP frame fallito: {r['error']}",
            }

    return {
        "serial_output": serial_output,
        "lines": serial_lines,
        "frame_paths": local_frame_paths,
        "error": None,
    }


def cleanup_session(session_id: str) -> None:
    """
    Rimuove file temporanei sul Raspberry e localmente.
    """
    remote_dir    = f"{_RPI_TMP_BASE}/vcap_{session_id}"
    stdout_file   = f"{_RPI_TMP_BASE}/vcap_{session_id}_out.txt"
    err_file      = f"{_RPI_TMP_BASE}/vcap_{session_id}_err.txt"
    launch_file   = f"{_RPI_TMP_BASE}/vcap_{session_id}_launch.txt"

    _ssh(
        f"rm -rf {remote_dir} {stdout_file} {err_file} {launch_file} 2>/dev/null",
        timeout=15,
    )

    local_dir = f"{_LOCAL_TMP_BASE}/vcap_local_{session_id}"
    if os.path.isdir(local_dir):
        import shutil
        shutil.rmtree(local_dir, ignore_errors=True)
