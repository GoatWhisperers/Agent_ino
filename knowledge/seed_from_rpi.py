"""
Importa nel DB i progetti reali presenti sul Raspberry Pi.

Progetti:
  1. soil_sensor_monitor   — Modbus RS485, MQTT su W5500, AsyncWebServer, Preferences
  2. microturbina_monitor   — stessa stack, monitoraggio microturbina
  3. forno_tamtam_v2        — MAX6675, OLED SSD1306, relè, FSM, timer cottura
  4. avvolgitore_tubo_flat  — stepper ISR, EEPROM, proximity sensors, WebServer

Uso:
  source .venv/bin/activate
  python knowledge/seed_from_rpi.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from knowledge import db as kdb
from knowledge.semantic import index_snippet

# ─── SSH helper ────────────────────────────────────────────────────────────────

RPI_HOST = "192.168.1.167"
RPI_USER = "lele"
RPI_PASS = "pippopippo33$$"


def ssh_read(remote_path: str) -> str:
    """Legge un file dal Raspberry Pi via SSH."""
    r = subprocess.run(
        ["sshpass", "-p", RPI_PASS,
         "ssh", "-o", "StrictHostKeyChecking=no",
         f"{RPI_USER}@{RPI_HOST}", f"cat {remote_path}"],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        print(f"  ⚠️  Impossibile leggere {remote_path}: {r.stderr.strip()[:100]}")
        return ""
    return r.stdout


# ─── Dati librerie ─────────────────────────────────────────────────────────────

LIBRARIES = [
    # Stack base ESP32
    ("WiFi",             "WiFi built-in ESP32 — connessione client/AP", "built-in", ""),
    ("WebServer",        "Web server HTTP sincrono built-in ESP32, semplice e leggero", "built-in", ""),
    ("Preferences",      "Storage key-value persistente su NVS Flash ESP32, sostituisce EEPROM", "built-in", ""),
    ("EEPROM",           "Accesso alla memoria EEPROM/NVS ESP32 con get/put", "built-in", ""),
    ("Wire",             "Protocollo I2C built-in — SDA/SCL", "built-in", ""),
    ("SPI",              "Protocollo SPI built-in — MOSI/MISO/SCK/CS", "built-in", ""),
    # Stack Async
    ("ESPAsyncWebServer", "Web server asincrono non-blocking — gestisce JSON API, upload file, WebSocket", "me-no-dev/ESPAsyncWebServer", ""),
    ("AsyncTCP",          "TCP asincrono richiesto da ESPAsyncWebServer", "me-no-dev/AsyncTCP", ""),
    # Ethernet
    ("Ethernet",          "Stack Ethernet W5100/W5500 via SPI — IP statico o DHCP", "arduino-libraries/Ethernet", ""),
    # Modbus
    ("ModbusMaster",      "Client Modbus RTU su RS485/UART — legge/scrive registri holding/input", "4-20ma/ModbusMaster", ""),
    # MQTT
    ("PubSubClient",      "Client MQTT per ESP32/Arduino — publish/subscribe con broker MQTT", "knolleary/PubSubClient", ""),
    # Display
    ("Adafruit_GFX",      "Libreria grafica Adafruit base — linee, cerchi, testo, bitmap", "adafruit/Adafruit GFX Library", ""),
    ("Adafruit_SSD1306",  "Driver display OLED SSD1306 128x64 via I2C o SPI", "adafruit/Adafruit SSD1306", ""),
    # Temperatura
    ("max6675",           "Driver termocoppia MAX6675 via SPI — lettura temperatura fino a 1024°C", "adafruit/MAX6675 library", ""),
    # Stepper
    ("AccelStepper",      "Controllo motore stepper con accelerazione/decelerazione, multi-motore", "waspinator/AccelStepper", ""),
    # JSON
    ("ArduinoJson",       "Serializzazione/deserializzazione JSON per ESP32, usato con WebServer e MQTT", "bblanchon/ArduinoJson", ""),
    # NTP / Time
    ("time",              "Funzioni time POSIX built-in ESP32 — gettimeofday, struct tm", "built-in", ""),
]


# ─── Funzione helper snippet ────────────────────────────────────────────────────

def add_project_snippet(task: str, code: str, board: str, libraries: list, tags: list):
    if not code.strip():
        print(f"  ⚠️  Codice vuoto per '{task[:50]}' — skip")
        return
    sid = kdb.add_snippet(
        task=task,
        code=code,
        board=board,
        libraries=libraries,
        tags=tags,
    )
    index_snippet(sid, task, code, tags)
    print(f"  ✅ Snippet aggiunto: {sid[:8]}... — {task[:70]}")
    return sid


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    kdb.init_db()
    print("\n=== SEEDING DB DAI PROGETTI RASPBERRY PI ===\n")

    # ── 1. Librerie ─────────────────────────────────────────────────────────────
    print("[1/5] Aggiunta librerie...")
    for name, description, source, install_cmd in LIBRARIES:
        # Controlla se già presente
        import sqlite3
        conn = sqlite3.connect(str(ROOT / "knowledge" / "arduino_agent.db"))
        cur = conn.cursor()
        cur.execute("SELECT name FROM libraries WHERE name = ?", (name,))
        existing = cur.fetchone()
        conn.close()

        if existing:
            print(f"  ↩️  {name} già presente")
        else:
            kdb.add_library(name=name, description=description, source=source)
            print(f"  ✅ {name}")

    # ── 2. soil_sensor_monitor ──────────────────────────────────────────────────
    print("\n[2/5] soil_sensor_monitor...")
    soil_code = ssh_read("~/projects/soil_sensor_monitor/final_integration/src/main.cpp")

    if soil_code:
        # Snippet principale: sistema completo
        add_project_snippet(
            task="Monitor sensori suolo NPK Modbus RS485 con dashboard web, MQTT via Ethernet W5500 e storage configurazione Preferences su ESP32",
            code=soil_code,
            board="esp32:esp32:esp32dev",
            libraries=["ESPAsyncWebServer", "AsyncTCP", "ModbusMaster", "PubSubClient", "Ethernet", "Preferences", "WiFi", "SPI"],
            tags=["modbus", "rs485", "mqtt", "ethernet", "w5500", "async-webserver", "preferences", "soil-sensor", "npk", "esp32"],
        )

        # Estrai pattern Modbus scanning — blocco identificabile nel sorgente
        modbus_pattern = _extract_section(soil_code, "SCAN", lines=80)
        if modbus_pattern:
            add_project_snippet(
                task="Scan automatico dispositivi Modbus RTU RS485 su ESP32 con baud rate multipli (2400, 4800, 9600, 19200) e slave ID 1-255",
                code=modbus_pattern,
                board="esp32:esp32:esp32dev",
                libraries=["ModbusMaster"],
                tags=["modbus", "rs485", "scanner", "uart", "serial2"],
            )

    # ── 3. microturbina_monitor ─────────────────────────────────────────────────
    print("\n[3/5] microturbina_monitor...")
    turbina_code = ssh_read("~/projects/microturbina_monitor/src/main.cpp")

    if turbina_code:
        add_project_snippet(
            task="Monitor microturbina con lettura parametri Modbus RS485, pubblicazione MQTT via W5500 Ethernet, dashboard web asincrona e storage NVS su ESP32",
            code=turbina_code,
            board="esp32:esp32:esp32dev",
            libraries=["ESPAsyncWebServer", "AsyncTCP", "ModbusMaster", "PubSubClient", "Ethernet", "Preferences", "WiFi", "SPI"],
            tags=["modbus", "rs485", "mqtt", "ethernet", "w5500", "async-webserver", "turbine", "monitoring", "esp32"],
        )

    # ── 4. forno_tamtam_v2 ──────────────────────────────────────────────────────
    print("\n[4/5] forno_tamtam_v2...")
    forno_code = ssh_read("~/projects/forno_tamtam_v2/src/main.cpp")

    if forno_code:
        # Progetto completo
        add_project_snippet(
            task="Centralina forno pizzeria con termocoppia MAX6675, display OLED SSD1306, 3 relè canal calore con sfasamento ciclico, FSM stato forno, timer cottura con buzzer e web interface WiFi su ESP32",
            code=forno_code,
            board="esp32:esp32:esp32dev",
            libraries=["max6675", "Adafruit_GFX", "Adafruit_SSD1306", "WebServer", "Preferences", "Wire", "WiFi"],
            tags=["max6675", "thermocouple", "oled", "ssd1306", "relay", "fsm", "temperature-control", "pid", "webserver", "timer", "buzzer", "esp32"],
        )

        # Estrai pattern lettura MAX6675 con media trimmed
        tc_pattern = _extract_section(forno_code, "readOvenC", lines=60)
        if tc_pattern:
            add_project_snippet(
                task="Lettura robusta termocoppia MAX6675 su ESP32 con media trimmed (rimuove min/max), rilevamento fault e offset calibrazione",
                code=tc_pattern,
                board="esp32:esp32:esp32dev",
                libraries=["max6675"],
                tags=["max6675", "thermocouple", "temperature", "spi", "trimmed-mean", "fault-detection"],
            )

        # Estrai pattern trend temperatura
        trend_pattern = _extract_section(forno_code, "updateTrend", lines=50)
        if trend_pattern:
            add_project_snippet(
                task="Calcolo trend temperatura su buffer circolare ESP32: rileva salita, discesa, stabile su N campioni con soglia configurabile",
                code=trend_pattern,
                board="esp32:esp32:esp32dev",
                libraries=[],
                tags=["trend", "temperature", "circular-buffer", "history", "analytics"],
            )

        # Estrai FSM
        fsm_pattern = _extract_section(forno_code, "TREND_RISING", lines=40)
        if fsm_pattern:
            add_project_snippet(
                task="FSM controllo temperatura forno: stati TREND_RISING/FALLING/STABLE/UNKNOWN con isteresi e latch anti-chatter su ESP32",
                code=fsm_pattern,
                board="esp32:esp32:esp32dev",
                libraries=[],
                tags=["fsm", "state-machine", "temperature", "hysteresis", "latch"],
            )

    # ── 5. avvolgitore_tubo_flat ────────────────────────────────────────────────
    print("\n[5/5] avvolgitore_tubo_flat...")
    avvol_code = ssh_read("~/projects/avvolgitore_tubo_flat/src/main.cpp")

    if avvol_code:
        # Progetto completo
        add_project_snippet(
            task="Avvolgitore tubo flat con motore stepper NEMA controllato via ISR timer ESP32, sensori proximity per fine-corsa, rampa accelerazione/decelerazione, calibrazione automatica, configurazione EEPROM e WebServer",
            code=avvol_code,
            board="esp32:esp32:esp32dev",
            libraries=["EEPROM", "WebServer", "WiFi"],
            tags=["stepper", "isr", "timer", "proximity", "endstop", "ramp", "acceleration", "eeprom", "webserver", "motor-control", "esp32"],
        )

        # ISR stepper
        isr_pattern = _extract_section(avvol_code, "IRAM_ATTR onTimer", lines=50)
        if isr_pattern:
            add_project_snippet(
                task="ISR timer ESP32 per controllo stepper passo-passo con generazione impulsi STEP/DIR e accumulatore di fase — massima precisione temporale in IRAM",
                code=isr_pattern,
                board="esp32:esp32:esp32dev",
                libraries=[],
                tags=["isr", "timer", "stepper", "iram", "step-dir", "pulse-generator", "esp32"],
            )

        # EEPROM config pattern
        eeprom_pattern = _extract_section(avvol_code, "salvaConfig", lines=60)
        if eeprom_pattern:
            add_project_snippet(
                task="Salvataggio e caricamento configurazione su EEPROM ESP32 con magic number per validazione e struct ConfigData",
                code=eeprom_pattern,
                board="esp32:esp32:esp32dev",
                libraries=["EEPROM"],
                tags=["eeprom", "config", "persistence", "magic-number", "struct"],
            )

    print("\n=== SEEDING COMPLETATO ===")
    # Report finale
    import sqlite3
    conn = sqlite3.connect(str(ROOT / "knowledge" / "arduino_agent.db"))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM libraries"); print(f"Librerie nel DB: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM snippets");  print(f"Snippet nel DB:  {cur.fetchone()[0]}")
    conn.close()


# ─── Utility estrazione sezione ────────────────────────────────────────────────

def _extract_section(code: str, keyword: str, lines: int = 60) -> str:
    """Estrae N righe a partire dalla prima riga che contiene keyword."""
    code_lines = code.splitlines()
    for i, line in enumerate(code_lines):
        if keyword in line:
            end = min(i + lines, len(code_lines))
            return "\n".join(code_lines[i:end])
    return ""


if __name__ == "__main__":
    main()
