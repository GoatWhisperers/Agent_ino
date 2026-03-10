"""
Wrapper around arduino-cli for uploading sketches and reading serial output.

arduino-cli binary path: /home/lele/codex-openai/programmatore_di_arduini/bin/arduino-cli
Requires: pyserial
"""

import json
import subprocess
import threading
import time
from typing import Optional

import serial
import serial.tools.list_ports

ARDUINO_CLI = "/home/lele/codex-openai/programmatore_di_arduini/bin/arduino-cli"


def upload_sketch(
    binary_path: str,
    port: str,
    fqbn: str = "arduino:avr:uno",
) -> dict:
    """
    Upload a compiled .hex binary to an Arduino board via arduino-cli.

    Parameters
    ----------
    binary_path : str
        Absolute path to the compiled .hex file.
    port : str
        Serial port the board is connected to (e.g. "/dev/ttyUSB0").
    fqbn : str
        Fully Qualified Board Name (default: arduino:avr:uno).

    Returns
    -------
    dict with keys:
        success : bool
        error   : str | None
    """
    cmd = [
        ARDUINO_CLI,
        "upload",
        "--fqbn", fqbn,
        "--port", port,
        "--input-file", binary_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return {"success": False, "error": f"arduino-cli non trovato: {ARDUINO_CLI}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Timeout durante l'upload (>60s)"}

    if result.returncode == 0:
        return {"success": True, "error": None}

    error_msg = (result.stderr or result.stdout or "Upload fallito").strip()
    return {"success": False, "error": error_msg}


def read_serial(port: str, baud: int = 9600, duration_sec: int = 10) -> dict:
    """
    Read output from a serial port for a given number of seconds.

    Parameters
    ----------
    port : str
        Serial port to open (e.g. "/dev/ttyUSB0").
    baud : int
        Baud rate (default: 9600).
    duration_sec : int
        How many seconds to read before returning (default: 10).

    Returns
    -------
    dict with keys:
        output : str          – full captured text
        lines  : list[str]    – individual lines (stripped)
        error  : str | None
    """
    lines: list[str] = []
    error: Optional[str] = None

    try:
        ser = serial.Serial(port, baudrate=baud, timeout=1)
    except serial.SerialException as exc:
        return {"output": "", "lines": [], "error": str(exc)}

    # Reset Arduino (toggling DTR)
    ser.setDTR(False)
    time.sleep(0.1)
    ser.setDTR(True)
    time.sleep(0.5)
    ser.reset_input_buffer()

    deadline = time.monotonic() + duration_sec
    buffer = b""

    try:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            ser.timeout = min(1.0, remaining)
            chunk = ser.read(4096)
            if chunk:
                buffer += chunk
    except serial.SerialException as exc:
        error = str(exc)
    finally:
        ser.close()

    text = buffer.decode("utf-8", errors="replace")
    lines = [l.rstrip("\r") for l in text.splitlines() if l.strip()]

    return {"output": text, "lines": lines, "error": error}


def find_arduino_port() -> Optional[str]:
    """
    Detect the serial port of a connected Arduino board.

    First tries ``arduino-cli board list`` for authoritative detection;
    falls back to scanning known USB-serial VID/PID pairs via pyserial.

    Returns
    -------
    str | None
        The port string (e.g. "/dev/ttyUSB0") or None if not found.
    """
    # --- Metodo 1: arduino-cli board list (output JSON) ---
    try:
        result = subprocess.run(
            [ARDUINO_CLI, "board", "list", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            # Struttura JSON: lista di oggetti con chiave "port" e "matching_boards"
            for entry in data:
                boards = entry.get("matching_boards", [])
                if boards:  # board riconosciuta
                    port_info = entry.get("port", {})
                    address = port_info.get("address") or port_info.get("label")
                    if address:
                        return address
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError,
            KeyError, TypeError):
        pass

    # --- Metodo 2: pyserial – scansione VID/PID noti ---
    # Arduino Uno R3: VID=0x2341 PID=0x0043
    # Arduino Nano (CH340): VID=0x1A86 PID=0x7523
    # Arduino Nano (FTDI): VID=0x0403 PID=0x6001
    KNOWN_VIDS = {0x2341, 0x1A86, 0x0403, 0x10C4}

    for port_info in serial.tools.list_ports.comports():
        if port_info.vid is not None and port_info.vid in KNOWN_VIDS:
            return port_info.device

    return None
