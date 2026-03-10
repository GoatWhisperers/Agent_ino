# Raspberry Pi — Integrazione come programmatore remoto

Il Raspberry Pi (`programmatore-rpi`, IP `192.168.1.167`) è il programmatore fisico dell'agente. La scheda ESP32 è collegata via USB al Raspberry. È una macchina completa e autonoma per la programmazione ESP32/Arduino.

---

## Hardware

| Componente | Dettaglio |
|------------|-----------|
| Board | Raspberry Pi 3 Model B v1.2 |
| OS | Raspberry Pi OS Bookworm Lite 64-bit, aarch64 |
| RAM | 1 GB |
| SD | 64 GB |
| IP | 192.168.1.167 (statico) |
| Connessione | LAN cablata con server lele |
| Scheda collegata | ESP32-D0WD-V3 rev3.1 via CP2102, `/dev/ttyUSB0` |

---

## Tools installati (stato reale verificato)

| Tool | Path | Stato | Uso |
|------|------|-------|-----|
| **PlatformIO** 6.1.18 | `~/.platformio/penv/bin/pio` | ✅ funzionante | Compile + flash ESP32/Arduino |
| Platform `espressif32` | `~/.platformio/platforms/` | ✅ installata v6.12.0 | Toolchain ESP32 completa |
| `esptool` 5.1 | sistema | ✅ funzionante | Flash .bin diretto |
| `pyserial` | sistema | ✅ funzionante | Lettura seriale |
| `arduino-cli` 1.4.0 | `/usr/local/bin/` | ⚠️ senza core | Presente ma nessun core installato |
| `minicom` / `picocom` | sistema | ✅ funzionante | Monitor seriale manuale |
| `adafruit-ampy` | sistema | ✅ installato | MicroPython |

**Nota**: `pio` non è in `$PATH` di default — va invocato sempre con il path completo `~/.platformio/penv/bin/pio`.

---

## Progetti presenti sul Raspberry

Il Raspberry ha già una collezione di progetti reali in `~/projects/`:

```
~/projects/
├── arduino/
├── esp32/
├── microturbina_monitor/
├── soil_sensor_monitor/
├── avvolgitore_tubo_flat/
├── forno_tamtam_v2/
├── heltec/
├── meshtastic_lilygo/
├── templates/
└── test_projects/
    └── esp32_blink/     ← progetto di test base
```

Tutti i progetti usano struttura PlatformIO (`platformio.ini` + `src/main.cpp`).

**platformio.ini standard per ESP32:**
```ini
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
upload_speed = 921600
```

---

## Come funziona il flusso automatico (agente)

Il flusso attuale dell'agente usa arduino-cli sul server per compilare e esptool sul Raspberry per flashare:

```
server lele
  │
  ├─ arduino-cli compile (esp32:esp32:esp32) → .bin
  │
  ├─ SCP .bin → Raspberry /tmp/
  │
  └─ SSH Raspberry
        ├─ esptool write_flash → flash ESP32
        ├─ read_serial.py → legge seriale N secondi
        └─ ritorna stdout al server → MI50 valuta
```

Gestito da `agent/remote_uploader.py`. Rilevamento automatico: se `fqbn` contiene `esp32`, usa il flusso remoto.

---

## Uso diretto di PlatformIO sul Raspberry (alternativa)

Il Raspberry può compilare e flashare in autonomia — utile per debug manuale o per evitare di passare dal server.

```bash
# Compile + flash di un progetto esistente
ssh lele@192.168.1.167 \
  "cd ~/projects/NOME_PROGETTO && ~/.platformio/penv/bin/pio run -t upload --upload-port /dev/ttyUSB0"

# Solo compilazione
ssh lele@192.168.1.167 \
  "cd ~/projects/NOME_PROGETTO && ~/.platformio/penv/bin/pio run"

# Flash script già pronto (usa ~/.platformio/penv/bin/pio internamente)
ssh lele@192.168.1.167 "~/scripts/rpi_flash_esp32.sh ~/projects/NOME_PROGETTO /dev/ttyUSB0"
```

**Nota**: `rpi_flash_esp32.sh` chiama `pio` senza path completo → fallisce se lanciato via SSH diretta. Va modificato per usare `~/.platformio/penv/bin/pio` oppure invocato in una shell che ha il PATH corretto.

---

## Scripts disponibili

```
~/scripts/rpi_detect_devices.sh      ← rileva board USB collegate ✅
~/scripts/rpi_flash_esp32.sh         ← compile+flash via pio (path pio da fixare)
~/scripts/rpi_monitor_serial.sh      ← monitor seriale con timestamp ✅
~/scripts/rpi_health_check.sh        ← verifica stato sistema ✅
~/scripts/rpi_sync_from_programmatore.sh ← sync dal nodo 192.168.1.166
~/read_serial.py                     ← lettura seriale con timeout ✅ (usato dall'agente)
```

`read_serial.py` accetta: `python3 ~/read_serial.py <port> <baud> <secondi>`
L'output informativo va su stderr — stdout contiene solo i dati seriali.

---

## Connessione manuale

```bash
# Accesso SSH
ssh lele@192.168.1.167

# Verificare scheda collegata
ssh lele@192.168.1.167 "~/scripts/rpi_detect_devices.sh"

# Flash manuale via esptool
ssh lele@192.168.1.167 \
  "esptool --port /dev/ttyUSB0 --baud 460800 write_flash 0x0 /tmp/sketch.bin"

# Monitor seriale con timeout
ssh lele@192.168.1.167 "python3 ~/read_serial.py /dev/ttyUSB0 115200 10"

# Monitor interattivo (ctrl+a ctrl+x per uscire)
ssh lele@192.168.1.167 "picocom -b 115200 /dev/ttyUSB0"
```

---

## Rapporto con altri nodi LAN

Dalla documentazione del Raspberry emerge un terzo nodo: **programmatore principale** a `192.168.1.166`, PC con laboratorio elettronica e repository master dei progetti. Il Raspberry ha SSH passwordless verso quel nodo. Non è coinvolto nel workflow dell'agente, ma i progetti `~/projects/` sul Raspberry sono sincronizzati da lì.

---

## Troubleshooting

**ESP32 non si connette (esptool "Failed to connect"):**
1. Tenere premuto BOOT sull'ESP32 durante l'avvio del flash
2. Provare baud ridotto: `baud_flash=115200` in `upload_and_read_remote()`
3. Verificare cavo USB (deve supportare dati)

**Permission denied su /dev/ttyUSB0:**
```bash
ssh lele@192.168.1.167 "groups | grep dialout"
# Se manca: sudo usermod -a -G dialout lele  (poi logout/login)
```

**pio: command not found via SSH:**
```bash
# Usare sempre il path completo
~/.platformio/penv/bin/pio --version
```
