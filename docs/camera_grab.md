# Sistema di Cattura Frame — Documentazione Completa

## Architettura

```
┌─────────────────────────────────────────────────────────────────────┐
│  SERVER (MI50/M40)                                                  │
│                                                                     │
│  agent/grab.py                                                      │
│  ├── grab_now(n, ms)          → cattura immediata (debug/analisi)   │
│  ├── start_serial_grab(...)   → avvia listener VCAP in background   │
│  ├── collect_grab(session_id) → raccoglie frame dopo l'esecuzione   │
│  └── cleanup_grab(session_id) → rimuove file temporanei             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ SSH / SCP
┌──────────────────────────────▼──────────────────────────────────────┐
│  RASPBERRY PI (192.168.1.167)                                        │
│                                                                     │
│  agent/grab_tool.py                                                 │
│  ├── modalità immediate  → cattura N frame subito, esce             │
│  └── modalità serial     → ascolta VCAP da ESP32, cattura su evento │
│                                                                     │
│  Storage: /dev/shm/grab_<session>/   ← RAM, NON la SD card         │
│           (453 MB disponibili, ~26 KB per frame = ~17.000 frame max)│
└──────────────────────────────┬──────────────────────────────────────┘
                               │ USB seriale
┌──────────────────────────────▼──────────────────────────────────────┐
│  ESP32                                                              │
│  → Serial.println("VCAP_START 5 200")  // 5 frame ogni 200ms       │
│  → Serial.println("VCAP_NOW led_on")   // singolo frame su evento  │
│  → Serial.println("VCAP_END")          // fine sessione            │
└─────────────────────────────────────────────────────────────────────┘
```

## Perché questo design

**Il problema**: i modelli (MI50/M40) sono lenti. Non possono reagire in tempo reale a
un LED che lampeggia a 500ms o un motore che parte. Se MI50 decidesse "voglio vedere
il LED acceso", il momento sarebbe già passato.

**La soluzione**: il modello pre-programma la cattura nel codice Arduino.
L'ESP32 sa quando avvengono gli eventi (è lui che li genera), quindi
comanda il Raspberry esattamente nel momento giusto via `Serial.println`.

**La RAM**: i frame vivono in `/dev/shm` (shared memory del kernel Linux),
garantita essere RAM su qualsiasi sistema Linux. Nessun byte va sulla SD card.
Il Raspberry ha 453 MB di `/dev/shm` disponibili.

**Cattura**: `rpicam-still` — diretto, senza daemon né server intermedi.
Overhead per frame: ~330ms (warm-up minimo con `-t 300 --immediate`).

---

## Tool 1 — grab_now (cattura immediata)

Usato dal modello per debug, analisi stato fisico statico, test camera.

```python
from agent.grab import grab_now

result = grab_now(
    n_frames    = 3,     # frame da catturare
    interval_ms = 500,   # ms tra un frame e il successivo
    width       = 640,   # pixel larghezza
    height      = 480,   # pixel altezza
    quality     = 75,    # qualità JPEG (0-100)
    timeout     = 60,    # timeout SSH in secondi
)

# result = {
#   "ok":          True,
#   "frame_paths": ["/tmp/grab_local_now_xxx/frame_000.jpg", ...],
#   "n_frames":    3,
#   "error":       None,
# }

# Passare i frame all'evaluator visivo:
from agent.evaluator import Evaluator
ev = Evaluator()
eval_result = ev.evaluate_visual(task, result["frame_paths"], serial_output="")
```

### Quando usarlo
- Test rapido della camera ("la camera funziona?")
- Analisi di uno stato fisico statico (es: "il circuito è assemblato correttamente?")
- Debug: vedere cosa sta inquadrando la camera
- Nessun ESP32 necessario

### Test da terminale
```bash
cd programmatore_di_arduini
source .venv/bin/activate
python agent/grab.py test 3 500   # 3 frame ogni 500ms
```

---

## Tool 2 — Flusso VCAP con ESP32

Per catturare eventi dinamici (LED che lampeggia, motori, display, ecc.).

### Lato agente (server)

```python
from agent.grab import start_serial_grab, collect_grab, cleanup_grab

# 1. Avvia listener prima dell'upload del firmware
session_id = start_serial_grab(
    port        = "/dev/ttyUSB0",
    baud        = 115200,
    timeout_sec = 30,     # timeout massimo attesa VCAP_END
    width       = 640,
    height      = 480,
    quality     = 75,
)

# 2. Carica il firmware (che contiene i VCAP_START/VCAP_NOW)
# ... upload_pio(...) ...

# 3. Raccogli frame e output seriale
result = collect_grab(session_id, wait_timeout=45)
cleanup_grab(session_id)

# result = {
#   "ok":            True,
#   "frame_paths":   ["/tmp/grab_local_ser_xxx/frame_000.jpg", ...],
#   "serial_output": "LED acceso\nLED spento\n...",
#   "lines":         ["LED acceso", "LED spento", ...],
#   "n_frames":      5,
#   "error":         None,
# }
```

### Lato ESP32 (sketch generato dal modello)

Il modello deve embedded i comandi VCAP nel codice Arduino nei punti giusti.

#### Pattern 1 — Sequenza di frame su evento

```cpp
void setup() {
  Serial.begin(115200);
  Serial.println("VCAP_READY");  // avvisa Raspberry che l'ESP32 è pronto
  delay(500);
  pinMode(LED_PIN, OUTPUT);
}

void loop() {
  // Prima di accendere il LED: chiedi 5 frame ogni 200ms
  Serial.println("VCAP_START 5 200");
  digitalWrite(LED_PIN, HIGH);
  Serial.println("LED acceso");
  delay(2000);

  digitalWrite(LED_PIN, LOW);
  Serial.println("LED spento");
  delay(1000);

  Serial.println("VCAP_END");  // Raspberry può uscire
  while(true) delay(1000);
}
```

#### Pattern 2 — Frame singolo su evento preciso

```cpp
void loop() {
  // Motore parte
  motorStart();
  Serial.println("VCAP_NOW motore_partenza");  // singolo frame istantaneo

  delay(1000);

  // Motore in regime
  Serial.println("VCAP_NOW motore_regime");

  motorStop();
  Serial.println("VCAP_NOW motore_stop");

  Serial.println("VCAP_END");
  while(true) delay(1000);
}
```

#### Pattern 3 — Cattura continua durante operazione

```cpp
void setup() {
  Serial.begin(115200);
  Serial.println("VCAP_READY");
  delay(200);

  // 10 frame ogni 300ms = ~3 secondi di ripresa
  Serial.println("VCAP_START 10 300");
}

void loop() {
  // ... logica sketch normale ...
  // I frame vengono catturati in background dal Raspberry
  Serial.println("stato: " + String(sensorValue));
  delay(100);
}
```

---

## Protocollo VCAP — Riferimento completo

| Segnale | Formato | Azione Raspberry |
|---------|---------|-----------------|
| `VCAP_READY` | `VCAP_READY` | Ack, nessuna azione |
| `VCAP_START` | `VCAP_START <N> <T>` | Cattura N frame ogni T ms (thread) |
| `VCAP_NOW` | `VCAP_NOW [label]` | Cattura 1 frame subito |
| `VCAP_END` | `VCAP_END` | Esce dal loop seriale |

**Note**:
- I segnali VCAP NON appaiono nell'output seriale passato all'Evaluator
- Le righe normali (`Serial.println("temperatura: 23.5")`) passano normalmente
- `VCAP_START` lancia un thread separato: il loop seriale continua a leggere
- Se arriva un altro `VCAP_START` mentre il precedente è in corso, viene ignorato
- `label` in `VCAP_NOW` è opzionale, aiuta a identificare il frame nel nome file

---

## grab_tool.py — Script Raspberry

`agent/grab_tool.py` viene deployato automaticamente su `~/grab_tool.py` dal server
(solo se cambiato, via confronto MD5).

**Tool di cattura**: `rpicam-still` — unico metodo, nessun servizio esterno richiesto.
I vecchi servizi MJPEG (camctl, ustreamer, picam_mjpeg) sono stati disabilitati
permanentemente (`systemctl disable --now`) e non partono più al boot.

```bash
# Modalità immediate (N frame ogni T ms)
python3 ~/grab_tool.py immediate <session_id> <n_frames> <interval_ms> [width] [height] [quality]

# Modalità serial (ascolta VCAP da ESP32)
python3 ~/grab_tool.py serial <session_id> <port> <baud> <timeout_sec> [width] [height] [quality]
```

Output sempre su stdout, ultima riga:
```
FRAMES:/dev/shm/grab_<session>/frame_000_081453.jpg,/dev/shm/grab_<session>/frame_001_081455.jpg
```
(Lista vuota `FRAMES:` se nessun frame catturato.)

---

## Gestione storage e cleanup

```
Sul Raspberry (RAM — /dev/shm):
  /dev/shm/grab_<session>/         ← cartella con i JPEG
  /dev/shm/grab_<session>_out.txt  ← stdout grab_tool (solo modalità background)

Sul server (tmp — /tmp):
  /tmp/grab_local_<session>/       ← frame copiati via SCP

cleanup_grab(session_id) rimuove entrambe le posizioni.
loop.py chiama cleanup_grab() automaticamente dopo collect_grab().
```

**Spazio RAM usato per sessione tipica**:
- 5 frame 640×480 JPEG q=75 ≈ 5 × 26KB = **130 KB**
- 10 frame 1280×960 JPEG q=85 ≈ 10 × 80KB = **800 KB**
- Limite pratico: centinaia di frame per sessione senza problemi

---

## Suggerimenti per il modello (MI50)

Quando MI50 genera un task che richiede valutazione visiva:

1. **Identifica gli eventi** da catturare (quando accade la cosa interessante)
2. **Scegli N e T**: pochi frame (3-10) e intervallo sufficiente (200-1000ms)
   - LED blink 500ms → `VCAP_START 6 250` (cattura per ~1.5 secondi)
   - Motore step → `VCAP_NOW step_partenza` + `VCAP_NOW step_fine`
   - Display update → `VCAP_NOW display_aggiornato`
3. **Posiziona VCAP_START prima** dell'evento (il thread parte quasi istantaneamente)
4. **Aggiungi VCAP_END** alla fine per non aspettare il timeout
5. **Non eccedere**: 10 frame max per sessione, /dev/shm ha 453MB ma non sprecare RAM

### Esempio di ragionamento MI50

```
Task: "fai lampeggiare LED pin 2 ogni 500ms e verifica visivamente"

→ L'evento interessante è il LED che cambia stato
→ Servo 6 frame ogni 300ms durante 2 cicli completi (6×300ms = 1.8s ≈ 3-4 lampeggi)
→ Posizione VCAP_START: prima del primo digitalWrite
→ Codice:
    Serial.println("VCAP_READY");
    delay(200);
    Serial.println("VCAP_START 6 300");
    for (int i = 0; i < 4; i++) {
        digitalWrite(2, HIGH);
        Serial.println("LED:ON");
        delay(500);
        digitalWrite(2, LOW);
        Serial.println("LED:OFF");
        delay(500);
    }
    Serial.println("VCAP_END");
```

---

## File coinvolti

| File | Dove | Funzione |
|------|------|---------|
| `agent/grab.py` | server | Tool Python per l'agente |
| `agent/grab_tool.py` | server → deployato su RPi | Script capture sul Raspberry |
| `agent/loop.py` | server | Usa grab.py nel flusso principale |
| `agent/evaluator.py` | server | `evaluate_visual()` analizza i frame con MI50 |
| `docs/webcam_raspberry.md` | server | Specifiche hardware camera IMX219 |

**File obsoleti** (non più usati):
- `agent/camera.py` → sostituito da `agent/grab.py`
- `agent/capture_frames.py` → sostituito da `agent/grab_tool.py`
