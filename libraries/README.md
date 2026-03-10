# Librerie Arduino/ESP32

Spazio dedicato alle librerie disponibili per l'agente.

## Struttura

```
libraries/
├── README.md          ← questo file
├── catalog.json       ← catalogo machine-readable (builtin + external)
├── lib_manager.py     ← tool Python per query, download, listing
├── builtin/           ← librerie built-in del framework ESP32 (copiate dal Raspberry)
│   ├── WiFi/
│   ├── Wire/
│   ├── BLE/
│   └── ...            (33 librerie totali)
└── external/          ← librerie di terze parti scaricate on-demand
    └── (vuota — si popola con lib_manager.py download <nome>)
```

## Come usare dal codice agente

```python
from libraries.lib_manager import query_for_task, get_info, get_headers, get_examples, download

# Trovare librerie per un task
libs = query_for_task("leggi temperatura da DHT22 e mostrala su display OLED")
# → [{"name": "DHT", "type": "external", "available": False, ...},
#    {"name": "Adafruit_SSD1306", "type": "external", ...}, ...]

# Info su una libreria specifica
info = get_info("WiFi")
# → {"name": "WiFi", "type": "builtin", "include": "WiFi.h", ...}

# Leggere i file header (per il modello)
headers = get_headers("WiFi")
# → ["/path/to/libraries/builtin/WiFi/src/WiFi.h", ...]

# Esempi disponibili
examples = get_examples("WiFi")
# → ["/path/to/.../WiFiScan.ino", "/path/to/.../WiFiClient.ino", ...]

# Scaricare una libreria esterna (la installa sul Raspberry e la copia qui)
result = download("DHT")
# → {"success": True, "path": "/path/to/libraries/external/DHT/", ...}
```

## Comandi da terminale

```bash
cd programmatore_di_arduini
source .venv/bin/activate

# Lista tutto il catalogo
python libraries/lib_manager.py list

# Cerca librerie per task
python libraries/lib_manager.py query "sensore ultrasonico e LED"

# Scarica una libreria esterna
python libraries/lib_manager.py download DHT
python libraries/lib_manager.py download ArduinoJson
```

## Librerie builtin (già disponibili, no lib_deps in platformio.ini)

| Nome | Include | Uso |
|------|---------|-----|
| WiFi | WiFi.h | Connessione WiFi STA/AP |
| Wire | Wire.h | Bus I2C (sensori, display) |
| SPI | SPI.h | Bus SPI |
| BLE | BLEDevice.h | Bluetooth Low Energy |
| BluetoothSerial | BluetoothSerial.h | Bluetooth Classic seriale |
| WebServer | WebServer.h | Server HTTP |
| HTTPClient | HTTPClient.h | Client HTTP/HTTPS |
| WiFiClientSecure | WiFiClientSecure.h | Connessioni TLS |
| EEPROM | EEPROM.h | Storage persistente |
| Preferences | Preferences.h | Key-value su NVS |
| LittleFS | LittleFS.h | File system su flash |
| SD | SD.h | Schede SD via SPI |
| ArduinoOTA | ArduinoOTA.h | Update OTA |
| Ticker | Ticker.h | Timer software |
| I2S | I2S.h | Audio digitale |
| ESPmDNS | ESPmDNS.h | Risoluzione .local |
| ... | | (33 totali) |

## Aggiungere nuove librerie al catalogo

Modifica `catalog.json` nella sezione `"external"` aggiungendo:
```json
"NomeLibreria": {
  "name": "Nome completo su PlatformIO",
  "category": "Sensor|Display|Communication|...",
  "description": "Cosa fa",
  "include": "NomeHeader.h",
  "pio_name": "autore/NomeLibreria",
  "installed": false,
  "use_case": "Quando usarla"
}
```
