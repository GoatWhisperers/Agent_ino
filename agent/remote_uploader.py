"""
Remote uploader — gestisce la programmazione di schede collegate al Raspberry Pi.

Flusso ESP32:
  1. Crea progetto PlatformIO sul Raspberry (~/projects/agente_<task>/)
  2. SCP del codice sorgente → src/main.cpp
  3. SCP delle librerie necessarie → lib/ (opzionale)
  4. pio compile sul Raspberry (toolchain nativa, verifica finale)
  5. pio upload sul Raspberry → ESP32
  6. read_serial.py → output seriale → ritorna al server per valutazione

Configurazione:
  Costanti RPI_* in questo file.
"""

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

# ── Configurazione Raspberry Pi ──────────────────────────────────────────────
RPI_HOST        = "YOUR_RPI_IP"
RPI_USER        = "lele"
RPI_PASSWORD    = "YOUR_PASSWORD"
RPI_SERIAL_PORT = "/dev/ttyUSB0"
RPI_PIO         = "~/.platformio/penv/bin/pio"
RPI_PROJECTS    = "~/projects"
RPI_READ_SERIAL = "~/read_serial.py"

# Librerie → nomi PlatformIO.
# Valore "" = built-in framework ESP32, NON aggiungere a lib_deps.
# Vedi libraries/catalog.json per la lista completa con descrizioni.
ARDUINO_TO_PIO = {
    # ── Built-in framework ESP32 (nessun lib_dep necessario) ──────────────────
    "ArduinoOTA":        "",
    "AsyncUDP":          "",
    "BLE":               "",
    "BluetoothSerial":   "",
    "DNSServer":         "",
    "EEPROM":            "",
    "ESP32":             "",
    "ESPmDNS":           "",
    "Ethernet":          "",
    "ETH":               "",
    "FFat":              "",
    "FS":                "",
    "HTTPClient":        "",
    "HTTPUpdate":        "",
    "HTTPUpdateServer":  "",
    "I2S":               "",
    "Insights":          "",
    "LittleFS":          "",
    "NetBIOS":           "",
    "Preferences":       "",
    "RainMaker":         "",
    "SD":                "",
    "SD_MMC":            "",
    "SimpleBLE":         "",
    "SPI":               "",
    "SPIFFS":            "",
    "Ticker":            "",
    "Update":            "",
    "USB":               "",
    "WebServer":         "",
    "WiFi":              "",
    "WiFiClientSecure":  "",
    "WiFiProv":          "",
    "Wire":              "",

    # ── Librerie esterne (PlatformIO registry) ────────────────────────────────
    "DHT sensor library":    "adafruit/DHT sensor library",
    "DHT":                   "adafruit/DHT sensor library",
    "OneWire":               "paulstoffregen/OneWire",
    "DallasTemperature":     "milesburton/DallasTemperature",
    "Servo":                 "arduino-libraries/Servo",
    "LiquidCrystal":         "arduino-libraries/LiquidCrystal",
    "LiquidCrystal_I2C":     "marcoschwartz/LiquidCrystal_I2C",
    "IRremote":              "z3t0/IRremote",
    "PubSubClient":          "knolleary/PubSubClient",
    "ArduinoJson":           "bblanchon/ArduinoJson",
    "FastLED":               "fastled/FastLED",
    "NewPing":               "teckel12/NewPing",
    "Adafruit_GFX":          "adafruit/Adafruit GFX Library",
    "Adafruit GFX Library":  "adafruit/Adafruit GFX Library",
    "Adafruit_SSD1306":      "adafruit/Adafruit SSD1306",
    "Adafruit SSD1306":      "adafruit/Adafruit SSD1306",
    "Adafruit_BME280":       "adafruit/Adafruit BME280 Library",
    "Adafruit BME280":       "adafruit/Adafruit BME280 Library",
    "Adafruit_MPU6050":      "adafruit/Adafruit MPU6050",
    "NTPClient":             "arduino-libraries/NTPClient",
    "TFT_eSPI":              "bodmer/TFT_eSPI",
    "Stepper":               "arduino-libraries/Stepper",
    "AccelStepper":          "waspinator/AccelStepper",
    "AsyncMqttClient":       "marvinroger/AsyncMqttClient",
}


# ── Utility SSH/SCP ──────────────────────────────────────────────────────────

def _sshpass_prefix() -> list[str]:
    return ["sshpass", "-p", RPI_PASSWORD]


def _ssh(cmd: str, timeout: int = 60) -> dict:
    """Esegue un comando via SSH sul Raspberry Pi."""
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


def _scp_file(local_path: str, remote_path: str, timeout: int = 30) -> dict:
    """Copia un file locale sul Raspberry Pi."""
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


def _scp_dir(local_path: str, remote_path: str, timeout: int = 60) -> dict:
    """Copia una directory locale sul Raspberry Pi (ricorsivo)."""
    full_cmd = _sshpass_prefix() + [
        "scp", "-r", "-o", "StrictHostKeyChecking=no",
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


# ── Setup progetto PlatformIO ─────────────────────────────────────────────────

def _make_project_name(task: str) -> str:
    """Genera un nome cartella sicuro dal task."""
    safe = re.sub(r"[^\w]", "_", task[:40]).strip("_")
    return f"agente_{safe}" or "agente_task"


def _prepare_main_cpp(ino_code: str) -> str:
    """
    Prepara il codice .ino per PlatformIO (main.cpp).
    Aggiunge #include <Arduino.h> se non presente.
    """
    if "#include <Arduino.h>" not in ino_code:
        return "#include <Arduino.h>\n\n" + ino_code
    return ino_code


def _make_platformio_ini(board: str = "esp32dev", libraries: list[str] = None) -> str:
    """Genera il platformio.ini per il progetto.

    NON usa lib_deps: le librerie sono pre-installate in ~/.platformio/lib/
    sul Raspberry, quindi lib_extra_dirs è sufficiente.
    lib_deps forzerebbe un download da internet che può fallire o timoutare.
    """
    return f"""[env:{board}]
platform = espressif32
board = {board}
framework = arduino
monitor_speed = 115200
upload_speed = 921600
lib_extra_dirs = ~/.platformio/lib
"""


def setup_pio_project(
    task: str,
    ino_code: str,
    libraries: list[str] = None,
    board: str = "esp32dev",
    extra_lib_dirs: list[str] = None,
) -> dict:
    """
    Crea (o ricrea) il progetto PlatformIO sul Raspberry Pi.

    task       : nome task (usato per la cartella)
    ino_code   : codice sorgente .ino
    libraries  : lista librerie necessarie (nomi Arduino)
    board      : board PlatformIO (default: esp32dev)
    extra_lib_dirs : cartelle librerie locali da copiare in lib/ (path assoluti)

    Ritorna {"success": bool, "project_dir": str, "error": str|None}
    """
    project_name = _make_project_name(task)
    remote_project = f"{RPI_PROJECTS}/{project_name}"

    # Crea struttura cartelle sul Raspberry
    r = _ssh(f"mkdir -p {remote_project}/src {remote_project}/lib", timeout=15)
    if r["returncode"] != 0:
        return {"success": False, "project_dir": "", "error": f"mkdir fallito: {r['stderr']}"}

    # Scrivi main.cpp in un file temporaneo e copialo
    main_cpp = _prepare_main_cpp(ino_code)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cpp", delete=False, encoding="utf-8") as f:
        f.write(main_cpp)
        tmp_cpp = f.name

    try:
        r = _scp_file(tmp_cpp, f"{remote_project}/src/main.cpp")
        if not r["success"]:
            return {"success": False, "project_dir": "", "error": f"SCP main.cpp fallito: {r['error']}"}
    finally:
        os.unlink(tmp_cpp)

    # Scrivi platformio.ini
    ini_content = _make_platformio_ini(board=board, libraries=libraries)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False, encoding="utf-8") as f:
        f.write(ini_content)
        tmp_ini = f.name

    try:
        r = _scp_file(tmp_ini, f"{remote_project}/platformio.ini")
        if not r["success"]:
            return {"success": False, "project_dir": "", "error": f"SCP platformio.ini fallito: {r['error']}"}
    finally:
        os.unlink(tmp_ini)

    # Copia librerie extra in lib/ se fornite
    for lib_dir in (extra_lib_dirs or []):
        if os.path.isdir(lib_dir):
            r = _scp_dir(lib_dir, f"{remote_project}/lib/")
            if not r["success"]:
                # Non bloccante — logghiamo ma continuiamo
                print(f"  [WARN] Copia libreria {lib_dir} fallita: {r['error']}")

    return {"success": True, "project_dir": remote_project, "error": None}


# ── Compile + Upload PlatformIO ───────────────────────────────────────────────

def compile_pio(project_dir: str, timeout: int = 300) -> dict:
    """
    Compila il progetto PlatformIO sul Raspberry Pi.

    Ritorna {"success": bool, "stdout": str, "stderr": str, "errors": list[str]}
    """
    cmd = f"cd {project_dir} && {RPI_PIO} run 2>&1"
    r = _ssh(cmd, timeout=timeout)

    combined = r["stdout"] + r["stderr"]
    success = r["returncode"] == 0

    # Estrai righe di errore
    errors = [
        line for line in combined.splitlines()
        if "error:" in line.lower() and ".cpp" in line.lower()
    ]

    return {
        "success": success,
        "stdout": combined,
        "errors": errors,
    }


def upload_pio(
    project_dir: str,
    port: str = RPI_SERIAL_PORT,
    timeout: int = 120,
) -> dict:
    """
    Flasha il firmware sul ESP32 via PlatformIO sul Raspberry Pi.

    Ritorna {"success": bool, "stdout": str, "error": str|None}
    """
    cmd = f"cd {project_dir} && {RPI_PIO} run -t upload --upload-port {port} 2>&1"
    r = _ssh(cmd, timeout=timeout)

    combined = r["stdout"] + r["stderr"]
    success = r["returncode"] == 0

    return {
        "success": success,
        "stdout": combined,
        "error": None if success else combined.strip()[-300:],
    }


# ── Lettura seriale ───────────────────────────────────────────────────────────

def read_serial_remote(
    port: str = RPI_SERIAL_PORT,
    baud: int = 115200,
    duration_sec: int = 10,
) -> dict:
    """
    Legge output seriale tramite read_serial.py sul Raspberry Pi.

    Ritorna {"output": str, "lines": list[str], "error": str|None}
    """
    cmd = f"python3 {RPI_READ_SERIAL} {port} {baud} {duration_sec}"
    r = _ssh(cmd, timeout=duration_sec + 20)

    text = r["stdout"]
    # Filtra null bytes e caratteri non stampabili dal boot ESP32
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(c for c in text if c.isprintable() or c == "\n")
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]

    if r["returncode"] != 0 and not text.strip():
        return {
            "output": "",
            "lines": [],
            "error": (r["stderr"] or "Nessun output dalla seriale").strip(),
        }
    return {"output": text, "lines": lines, "error": None}


# ── API principale ────────────────────────────────────────────────────────────

def upload_and_read_remote(
    task: str,
    ino_code: str,
    libraries: list[str] = None,
    board: str = "esp32dev",
    port: str = RPI_SERIAL_PORT,
    baud_serial: int = 115200,
    serial_duration: int = 10,
    extra_lib_dirs: list[str] = None,
) -> dict:
    """
    Flusso completo sul Raspberry Pi:
      setup progetto → compile pio → upload pio → read serial

    Ritorna {
        "success"        : bool,
        "serial_output"  : str,
        "lines"          : list[str],
        "error"          : str | None,
        "compile_stdout" : str,
        "upload_stdout"  : str,
    }
    """
    # 1. Setup progetto PlatformIO
    setup = setup_pio_project(
        task=task,
        ino_code=ino_code,
        libraries=libraries,
        board=board,
        extra_lib_dirs=extra_lib_dirs,
    )
    if not setup["success"]:
        return {
            "success": False, "serial_output": "", "lines": [],
            "error": f"Setup progetto fallito: {setup['error']}",
            "compile_stdout": "", "upload_stdout": "",
        }

    project_dir = setup["project_dir"]

    # 2. Compilazione sul Raspberry
    compile_result = compile_pio(project_dir)
    if not compile_result["success"]:
        return {
            "success": False, "serial_output": "", "lines": [],
            "error": "Compilazione pio fallita sul Raspberry",
            "compile_stdout": compile_result["stdout"],
            "upload_stdout": "",
        }

    # 3. Upload
    upload_result = upload_pio(project_dir, port=port)
    if not upload_result["success"]:
        return {
            "success": False, "serial_output": "", "lines": [],
            "error": f"Upload fallito: {upload_result['error']}",
            "compile_stdout": compile_result["stdout"],
            "upload_stdout": upload_result["stdout"],
        }

    # 4. Lettura seriale (aspetta il boot ESP32)
    time.sleep(2)
    serial_result = read_serial_remote(port=port, baud=baud_serial, duration_sec=serial_duration)

    return {
        "success": True,
        "serial_output": serial_result["output"],
        "lines": serial_result["lines"],
        "error": serial_result["error"],
        "compile_stdout": compile_result["stdout"],
        "upload_stdout": upload_result["stdout"],
    }


def is_reachable() -> bool:
    """Verifica che il Raspberry Pi sia raggiungibile via SSH."""
    r = _ssh("echo ok", timeout=10)
    return r["returncode"] == 0 and "ok" in r["stdout"]
