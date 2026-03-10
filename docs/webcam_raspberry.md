# Webcam Raspberry Pi — Specifiche e Utilizzo

## Hardware

| Parametro | Valore |
|-----------|--------|
| Modello | Sony IMX219 — Raspberry Pi Camera Module v2 |
| Risoluzione max | 3280×2464 (8 MP) |
| Interfaccia | CSI (ribbon cable, NON USB) |
| Device Linux | `/dev/video0` |
| Driver kernel | `unicam` (platform:3f801000.csi) |
| Tool capture | `rpicam-still` (v1.11.0, `/usr/bin/rpicam-still`) |

## Modi disponibili

| Risoluzione | FPS (10-bit) | FPS (8-bit) | Uso tipico |
|-------------|-------------|-------------|-----------|
| 640×480     | 206.65 fps  | 206.65 fps  | ✅ Usato dall'agente (veloce) |
| 1640×1232   | 41.85 fps   | 83.70 fps   | Analisi dettagliata |
| 1920×1080   | 47.57 fps   | 47.57 fps   | Full HD |
| 3280×2464   | 21.19 fps   | 21.19 fps   | Massima qualità |

## Tool installati

| Tool | Percorso | Stato |
|------|---------|-------|
| `rpicam-still` | `/usr/bin/rpicam-still` | ✅ installato |
| `libcamera-still` | — | ❌ non presente |
| `picamera2` | — | ❌ non installata |
| `fswebcam` | — | non verificato |

## Comandi rpicam-still

### Cattura base (640×480, JPEG)
```bash
rpicam-still -o /tmp/foto.jpg --nopreview --immediate -t 500 --width 640 --height 480 -q 75
```

### Opzioni principali

| Opzione | Descrizione | Default |
|---------|-------------|---------|
| `-o <path>` | File output | — |
| `--nopreview` | Nessuna finestra di preview | — |
| `--immediate` | Cattura subito senza warmup | — |
| `-t <ms>` | Timeout di warmup in ms | 5000 |
| `--width <px>` | Larghezza | nativo |
| `--height <px>` | Altezza | nativo |
| `-q <0-100>` | Qualità JPEG | 93 |
| `--gain <n>` | Guadagno analogico (utile con poca luce) | auto |
| `--shutter <us>` | Tempo esposizione in microsecondi | auto |
| `--brightness <f>` | Luminosità (-1.0 … 1.0) | 0.0 |
| `--contrast <f>` | Contrasto (0.0 … 32.0) | 1.0 |
| `--encoding jpg\|png\|bmp` | Formato output | jpg |
| `--list-cameras` | Mostra camera disponibili e modi | — |

### Cattura con luce scarsa
```bash
rpicam-still -o /tmp/foto.jpg --nopreview --immediate -t 2000 \
  --width 640 --height 480 -q 75 \
  --gain 8 --brightness 0.2
```

### Lista camera rilevate
```bash
rpicam-still --list-cameras
# Output:
# 0 : imx219 [3280x2464 10-bit RGGB] (/base/soc/i2c0mux/i2c@1/imx219@10)
#     Modes: 'SRGGB10_CSI2P' : 640x480 [206.65 fps] ...
```

### Cattura full resolution
```bash
rpicam-still -o /tmp/foto_full.jpg --nopreview --immediate -t 1000 -q 90
# Nessun --width/--height = risoluzione nativa 3280x2464
```

## Integrazione agente — Protocollo VCAP

Il protocollo VCAP permette all'ESP32 di comandare la cattura di frame via Serial.

### Segnali ESP32 → Raspberry

| Segnale | Descrizione |
|---------|-------------|
| `VCAP_READY` | ESP32 inizializzato, pronto |
| `VCAP_START N T` | Cattura N frame ogni T ms |
| `VCAP_NOW <label>` | Cattura un singolo frame con etichetta |
| `VCAP_END` | Fine sessione, script può uscire |

### Sketch ESP32 tipo con VCAP

```cpp
void setup() {
  Serial.begin(115200);
  Serial.println("VCAP_READY");
  delay(500);

  // Avvia sequenza di 5 frame ogni 1000ms
  Serial.println("VCAP_START 5 1000");
}

void loop() {
  // ... logica sketch ...

  // Cattura frame su evento specifico
  Serial.println("VCAP_NOW acceso");
  delay(100);
  Serial.println("VCAP_NOW spento");

  Serial.println("VCAP_END");
  while(true) delay(1000);
}
```

### Come funziona il flusso agente

```
ESP32                    Raspberry Pi              Server (MI50)
  │                           │                        │
  │─ VCAP_READY ─────────────>│                        │
  │─ VCAP_START 3 1000 ──────>│ avvia cattura thread   │
  │                           │──rpicam-still ──>│     │
  │─ (output seriale) ───────>│ log righe normali │    │
  │                           │──rpicam-still ──>│     │
  │                           │──rpicam-still ──>│     │
  │─ VCAP_END ───────────────>│ fine loop          │   │
  │                           │                        │
  │                           │<── SCP frames ─────────│
  │                           │    (collect_frames)    │
  │                           │                   MI50 valuta
```

### File coinvolti

| File | Dove gira | Funzione |
|------|----------|---------|
| `agent/camera.py` | server | deploy script, avvio/raccolta sessione |
| `agent/capture_frames.py` | Raspberry (via SSH) | legge seriale, cattura frame |

## Parametri in `capture_frames.py`

```python
cmd = [
    "rpicam-still",
    "-o", path,
    "--nopreview",
    "--immediate",
    "-t", "500",       # 500ms warmup (necessario per AGC/AWB)
    "--width", "640",
    "--height", "480",
    "-q", "75",
]
```

**Nota poca luce**: se l'ambiente è buio aumentare `-t` (es. `2000`) e aggiungere `--gain 8`.

## Dimensioni file tipiche (640×480, q=75)

Misurato in condizioni normali d'uso:
- JPEG 640×480 q=75: **~26 KB** (verificato 2026-03-09)
- Tempo cattura reale: ~330ms totali (warmup -t 500 + acquisizione)

## Limitazioni note

- **Posizione non ottimale**: la camera è fissa, il campo visivo deve essere allineato manualmente al LED/circuito da osservare
- **Poca luce**: l'ambiente di lavoro è poco illuminato — la camera IMX219 ha sensibilità discreta ma non eccezionale. Se i frame sono troppo scuri: aumentare gain o aggiungere illuminazione
- **Nessuna picamera2**: non installata, usare solo `rpicam-still`
- **Latenza**: ogni scatto richiede ~500ms di warmup + ~200ms di cattura. Per sequenze rapide ridurre `-t 200` (ma qualità AGC peggiore)
- **Un solo dispositivo**: `/dev/video0` è la CSI, non c'è webcam USB aggiuntiva

## Test rapido da SSH

```bash
# Connettiti al Raspberry
ssh lele@192.168.1.167

# Cattura un frame di test
rpicam-still -o /tmp/test.jpg --nopreview --immediate -t 500 --width 640 --height 480 -q 75

# Verifica che il file sia stato creato e abbia dimensione ragionevole
ls -lh /tmp/test.jpg

# Copialo sul server per vederlo
# (dal server):
sshpass -p 'pippopippo33$$' scp lele@192.168.1.167:/tmp/test.jpg /tmp/rpi_test.jpg
```

## Configurazione Raspberry Pi

```
# /boot/firmware/config.txt
camera_auto_detect=1        # rileva automaticamente la camera CSI
dtoverlay=vc4-kms-v3d       # driver display/camera moderno
dtoverlay=dwc2,dr_mode=host # USB host mode
```
