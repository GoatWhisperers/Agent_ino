"""
Gestore librerie Arduino/ESP32 per l'agente.

Funzioni:
  - query(task_description) → librerie consigliate per il task
  - download(lib_name)      → scarica libreria esterna dal Raspberry via PlatformIO
  - list_installed()        → lista librerie esterne installate
  - get_headers(lib_name)   → percorso ai file .h della libreria
  - get_examples(lib_name)  → lista esempi disponibili
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

LIBRARIES_DIR = Path(__file__).parent
CATALOG_PATH  = LIBRARIES_DIR / "catalog.json"
BUILTIN_DIR   = LIBRARIES_DIR / "builtin"
EXTERNAL_DIR  = LIBRARIES_DIR / "external"

# Raspberry Pi
RPI_HOST     = "192.168.1.167"
RPI_USER     = "lele"
RPI_PASSWORD = "pippopippo33$$"
RPI_PIO      = "~/.platformio/penv/bin/pio"


def _load_catalog() -> dict:
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_catalog(catalog: dict):
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)


def _ssh(cmd: str, timeout: int = 120) -> dict:
    import shutil
    if shutil.which("sshpass") is None:
        return {"returncode": -1, "stdout": "", "stderr": "sshpass non trovato"}
    full_cmd = ["sshpass", "-p", RPI_PASSWORD, "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                f"{RPI_USER}@{RPI_HOST}", cmd]
    r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
    return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}


def _scp_dir(remote_path: str, local_path: str, timeout: int = 60) -> dict:
    import shutil
    if shutil.which("sshpass") is None:
        return {"success": False, "error": "sshpass non trovato"}
    full_cmd = ["sshpass", "-p", RPI_PASSWORD,
                "scp", "-r", "-o", "StrictHostKeyChecking=no",
                f"{RPI_USER}@{RPI_HOST}:{remote_path}", local_path]
    r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
    return {"success": r.returncode == 0,
            "error": (r.stderr or r.stdout).strip() if r.returncode != 0 else None}


# ── API pubblica ───────────────────────────────────────────────────────────────

def list_all() -> dict:
    """Ritorna il catalogo completo (builtin + external)."""
    c = _load_catalog()
    return {"builtin": list(c["builtin"].keys()),
            "external": list(c["external"].keys())}


def list_installed() -> list[str]:
    """Ritorna le librerie esterne già scaricate."""
    if not EXTERNAL_DIR.exists():
        return []
    return [d.name for d in EXTERNAL_DIR.iterdir() if d.is_dir()]


def get_info(lib_name: str) -> dict | None:
    """Info su una libreria (builtin o external). None se non trovata."""
    c = _load_catalog()
    if lib_name in c["builtin"]:
        info = dict(c["builtin"][lib_name])
        info["type"] = "builtin"
        info["available"] = True
        return info
    if lib_name in c["external"]:
        info = dict(c["external"][lib_name])
        info["type"] = "external"
        info["available"] = info["installed"] or (EXTERNAL_DIR / lib_name).exists()
        return info
    return None


def get_headers(lib_name: str) -> list[str]:
    """Ritorna i percorsi assoluti dei file .h della libreria."""
    c = _load_catalog()
    if lib_name in c["builtin"]:
        p = LIBRARIES_DIR / c["builtin"][lib_name]["headers_path"]
    elif lib_name in c["external"]:
        p = EXTERNAL_DIR / lib_name / "src"
        if not p.exists():
            p = EXTERNAL_DIR / lib_name
    else:
        return []
    return [str(h) for h in p.rglob("*.h")] if p.exists() else []


def get_examples(lib_name: str) -> list[str]:
    """Ritorna i percorsi assoluti degli esempi .ino della libreria."""
    c = _load_catalog()
    if lib_name in c["builtin"]:
        ep = c["builtin"][lib_name].get("examples_path")
        if ep:
            p = LIBRARIES_DIR / ep
        else:
            return []
    elif lib_name in c["external"]:
        p = EXTERNAL_DIR / lib_name / "examples"
    else:
        return []
    return [str(e) for e in p.rglob("*.ino")] if p.exists() else []


def query_for_task(task_description: str) -> list[dict]:
    """
    Suggerisce librerie rilevanti per un task (ricerca per parole chiave).
    Ritorna lista di dict {name, type, description, include, pio_name}.
    """
    task_lower = task_description.lower()
    keywords_map = {
        # WiFi/Rete
        "wifi": ["WiFi", "WebServer", "HTTPClient", "ESPmDNS", "ArduinoOTA"],
        "http": ["HTTPClient", "WebServer"],
        "https": ["WiFiClientSecure", "HTTPClient"],
        "mqtt": ["PubSubClient", "AsyncMQTT"],
        "web": ["WebServer", "HTTPClient"],
        "api": ["HTTPClient", "ArduinoJson", "WiFiClientSecure"],
        "json": ["ArduinoJson"],
        "ota": ["ArduinoOTA", "HTTPUpdate"],
        # Bluetooth
        "bluetooth": ["BluetoothSerial", "BLE"],
        "ble": ["BLE", "SimpleBLE"],
        "bt": ["BluetoothSerial"],
        # Display
        "oled": ["Adafruit_SSD1306", "Adafruit_GFX"],
        "display": ["Adafruit_SSD1306", "LiquidCrystal_I2C", "TFT_eSPI"],
        "lcd": ["LiquidCrystal_I2C"],
        "tft": ["TFT_eSPI"],
        "led strip": ["FastLED"],
        "neopixel": ["FastLED"],
        "ws2812": ["FastLED"],
        "rgb": ["FastLED"],
        # Sensori
        "dht": ["DHT"],
        "dht11": ["DHT"],
        "dht22": ["DHT"],
        "temperatura": ["DHT", "DallasTemperature", "Adafruit_BME280"],
        "temperature": ["DHT", "DallasTemperature", "Adafruit_BME280"],
        "umidità": ["DHT", "Adafruit_BME280"],
        "humidity": ["DHT", "Adafruit_BME280"],
        "pressione": ["Adafruit_BME280"],
        "pressure": ["Adafruit_BME280"],
        "bme280": ["Adafruit_BME280"],
        "ds18b20": ["DallasTemperature", "OneWire"],
        "1-wire": ["OneWire", "DallasTemperature"],
        "ultrason": ["NewPing"],
        "hc-sr04": ["NewPing"],
        "distanza": ["NewPing"],
        "distance": ["NewPing"],
        "accelerometr": ["Adafruit_MPU6050"],
        "giroscopio": ["Adafruit_MPU6050"],
        "mpu6050": ["Adafruit_MPU6050"],
        "imu": ["Adafruit_MPU6050"],
        # Attuatori
        "servo": ["Servo"],
        "stepper": ["AccelStepper", "Stepper"],
        "motore passo": ["AccelStepper", "Stepper"],
        # Storage
        "eeprom": ["EEPROM"],
        "preferences": ["Preferences"],
        "nvs": ["Preferences"],
        "flash": ["LittleFS", "SPIFFS"],
        "file": ["LittleFS", "SD"],
        "sd card": ["SD"],
        "spiffs": ["SPIFFS"],
        "littlefs": ["LittleFS"],
        # Bus
        "i2c": ["Wire"],
        "spi": ["SPI"],
        "i2s": ["I2S"],
        "audio": ["I2S"],
        # IR / telecomando
        "infraross": ["IRremote"],
        "telecomando": ["IRremote"],
        "ir": ["IRremote"],
        # Tempo
        "ntp": ["NTPClient"],
        "orologio": ["NTPClient"],
        "orario": ["NTPClient"],
        "ticker": ["Ticker"],
        "timer": ["Ticker"],
        # Comunicazione device-to-device
        "esp-now": ["ESP_NOW"],
        "espnow": ["ESP_NOW"],
        "peer": ["ESP_NOW"],
    }

    suggested = {}
    for keyword, libs in keywords_map.items():
        if keyword in task_lower:
            for lib in libs:
                if lib not in suggested:
                    suggested[lib] = 0
                suggested[lib] += 1

    # Ordina per rilevanza
    c = _load_catalog()
    result = []
    for lib_name, score in sorted(suggested.items(), key=lambda x: -x[1]):
        info = None
        if lib_name in c["builtin"]:
            info = dict(c["builtin"][lib_name])
            info["type"] = "builtin"
            info["available"] = True
            info["relevance"] = score
        elif lib_name in c["external"]:
            info = dict(c["external"][lib_name])
            info["type"] = "external"
            info["available"] = info["installed"] or (EXTERNAL_DIR / lib_name).exists()
            info["relevance"] = score
        if info:
            result.append(info)

    return result


def download(lib_name: str) -> dict:
    """
    Scarica una libreria esterna tramite PlatformIO sul Raspberry Pi,
    poi la copia localmente in libraries/external/<lib_name>/.

    Ritorna {"success": bool, "path": str, "error": str|None}
    """
    c = _load_catalog()
    if lib_name not in c["external"]:
        return {"success": False, "path": "", "error": f"Libreria '{lib_name}' non nel catalogo"}

    lib_info = c["external"][lib_name]
    pio_name = lib_info.get("pio_name", "")
    if not pio_name:
        return {"success": False, "path": "", "error": f"Nessun nome PlatformIO per '{lib_name}'"}

    # Directory destinazione locale
    dest = EXTERNAL_DIR / lib_name
    if dest.exists():
        return {"success": True, "path": str(dest), "error": None}

    print(f"  Scarico '{pio_name}' sul Raspberry...")

    # Installa la libreria globalmente sul Raspberry
    install_cmd = f"{RPI_PIO} pkg install -g --library \"{pio_name}\" 2>&1"
    r = _ssh(install_cmd, timeout=120)
    if r["returncode"] != 0:
        return {"success": False, "path": "",
                "error": f"pio install fallito: {(r['stdout'] + r['stderr'])[-300:]}"}

    # Trova dove PlatformIO l'ha messa
    find_cmd = f"find ~/.platformio/lib -maxdepth 2 -name '*.h' | head -5"
    r2 = _ssh(find_cmd, timeout=15)
    # Prendi il nome directory dalla prima riga
    lines = [l for l in r2["stdout"].splitlines() if l.strip()]
    if not lines:
        return {"success": False, "path": "",
                "error": "Libreria installata ma non trovata in ~/.platformio/lib"}

    # La directory è 2 livelli sopra il primo .h
    lib_dir_remote = str(Path(lines[0]).parent.parent)

    # Copia localmente
    dest.mkdir(parents=True, exist_ok=True)
    scp_result = _scp_dir(f"{lib_dir_remote}/*", str(dest), timeout=60)
    if not scp_result["success"]:
        return {"success": False, "path": "",
                "error": f"SCP fallito: {scp_result['error']}"}

    # Aggiorna catalogo
    c["external"][lib_name]["installed"] = True
    _save_catalog(c)

    print(f"  Libreria '{lib_name}' scaricata in {dest}")
    return {"success": True, "path": str(dest), "error": None}


def print_summary():
    """Stampa un sommario leggibile del catalogo."""
    c = _load_catalog()
    print(f"\n{'='*60}")
    print(f"LIBRERIE BUILTIN ESP32 ({len(c['builtin'])} totali)")
    print(f"{'='*60}")
    for name, info in c["builtin"].items():
        print(f"  {name:<20} [{info['category']:<22}] {info['include'] or '—'}")

    installed = list_installed()
    print(f"\n{'='*60}")
    print(f"LIBRERIE ESTERNE ({len(c['external'])} nel catalogo, {len(installed)} installate)")
    print(f"{'='*60}")
    for name, info in c["external"].items():
        is_inst = name in installed or info.get("installed", False)
        status = "✅" if is_inst else "  "
        print(f"  {status} {name:<22} [{info['category']:<22}] {info['include']}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "list":
            print_summary()
        elif cmd == "download" and len(sys.argv) > 2:
            result = download(sys.argv[2])
            print(result)
        elif cmd == "query" and len(sys.argv) > 2:
            task = " ".join(sys.argv[2:])
            libs = query_for_task(task)
            print(f"\nLibrerie suggerite per: '{task}'")
            for lib in libs:
                avail = "✅ disponibile" if lib["available"] else "⬇ da scaricare"
                print(f"  {lib['name']:<22} {avail} — {lib['description']}")
        else:
            print("Uso: python lib_manager.py [list | download <nome> | query <task>]")
    else:
        print_summary()
