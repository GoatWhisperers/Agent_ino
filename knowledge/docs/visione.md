# Sistema di Visione — Debug Visivo con Webcam

Il sistema di visione permette a MI50 di valutare il funzionamento di un programma ESP32 guardando direttamente cosa succede nel mondo fisico, tramite la webcam CSI sul Raspberry Pi.

---

## Architettura

```
ESP32 (firmware)
  │  Serial.println("VCAP_START 6 500")
  ▼
Raspberry Pi (capture_frames.py)
  │  legge seriale + intercetta VCAP_*
  │  rpicam-still → /tmp/vcap_SESSION/ (tmpfs, sicuro per SD)
  ▼
server lele (camera.py)
  │  SCP frame → /tmp/vcap_local_SESSION/
  ▼
MI50 — Qwen3.5-9B multimodale
  │  vede i frame + legge output seriale
  │  "vedo il LED lampeggiare ogni ~500ms ✅"
  ▼
loop.py — decisione: successo / riscrittura
```

---

## Protocollo VCAP (ESP32 → Raspberry via seriale)

Il generatore (M40) include automaticamente questi segnali nel codice ESP32 in base al piano di MI50:

| Segnale | Formato | Significato |
|---------|---------|-------------|
| `VCAP_READY` | `Serial.println("VCAP_READY")` | Setup completato, ESP32 pronto |
| `VCAP_START` | `Serial.println("VCAP_START 6 500")` | Cattura 6 frame ogni 500ms |
| `VCAP_NOW` | `Serial.println("VCAP_NOW led_on")` | Cattura singolo frame, labellato |
| `VCAP_END` | `Serial.println("VCAP_END")` | Fine sequenza, script può uscire |

I segnali VCAP vengono filtrati dall'output seriale normale — non appaiono nella valutazione testuale.

---

## Qwen3.5-9B — Capacità multimodale

Il modello MI50 è **Qwen3.5-9B multimodale** (`Qwen3_5ForConditionalGeneration`). Ha un vision encoder integrato:
- Patch size: 16×16
- Hidden size vision: 1152
- Merge spaziale: 2×2
- Token immagine: `image_token_id: 248056`

Può rispondere a domande su immagini come: "vedi il LED lampeggiare?", "il display mostra il valore corretto?", "il motore si muove?"

---

## Parametri cattura (decisi da MI50 nella fase di planning)

Il piano del task include:
```json
{
  "approach": "...",
  "libraries_needed": [],
  "key_points": [],
  "vcap_frames": 6,
  "vcap_interval_ms": 500
}
```

- **`vcap_frames = 0`**: nessuna cattura visiva (task senza output fisico verificabile)
- **`vcap_frames > 0`**: cattura N frame a intervalli T ms

Esempi tipici:
| Task | vcap_frames | vcap_interval_ms |
|------|-------------|-----------------|
| LED blink 500ms | 6 | 500 |
| Display temperatura | 2 | 1000 |
| Motore stepper | 4 | 250 |
| Comunicazione seriale pura | 0 | — |

---

## Webcam sul Raspberry Pi

| Parametro | Valore |
|-----------|--------|
| Tipo | CSI (ribbon cable, non USB) |
| Device | `/dev/video0` (unicam) |
| Tool | `rpicam-still` |
| Python lib | `picamera2` |
| Risoluzione cattura | 640×480 |
| Qualità JPEG | 75% |

**SD card safe**: i frame vengono salvati in `/tmp/vcap_SESSION/` che è montato su tmpfs (RAM). Zero scritture su SD card durante la cattura.

---

## File del sistema

| File | Dove | Ruolo |
|------|------|-------|
| `agent/capture_frames.py` | server lele | Script deployato sul Raspberry via SCP |
| `agent/camera.py` | server lele | Orchestrazione SSH + SCP + sessioni |
| `agent/mi50_client.py` | server lele | Aggiunto `generate_with_images()` |
| `agent/evaluator.py` | server lele | Aggiunto `evaluate_visual()` |

---

## Flusso dettagliato in loop.py

```
[FASE 4 — RASPBERRY PI]
  1. deploy capture_frames.py sul Raspberry (una volta sola)
  2. setup progetto PlatformIO
  3. avvia sessione camera (SSH background: capture_frames.py in ascolto)
  4. pio upload → ESP32 boota
  5. ESP32 emette VCAP_READY → VCAP_START N T
  6. capture_frames.py cattura N frame → /tmp/vcap_SESSION/
  7. collect_frames(): aspetta fine sessione, SCP frame al server
  8. cleanup sessione

[FASE 5 — VALUTAZIONE]
  Se vcap_frames > 0:
    MI50.generate_with_images(frame_paths) → valutazione visiva
  Altrimenti:
    MI50.evaluate(serial_output) → valutazione testuale
```

---

## Esempio sketch generato (LED blink con VCAP)

```cpp
#include <Arduino.h>

void setup() {
  Serial.begin(115200);
  pinMode(2, OUTPUT);
  Serial.println("VCAP_READY");
  delay(200);
  Serial.println("VCAP_START 6 500");  // 6 frame ogni 500ms = 3 cicli
}

int count = 0;
void loop() {
  digitalWrite(2, HIGH);
  Serial.println("counter: " + String(count++));
  delay(500);
  digitalWrite(2, LOW);
  delay(500);
}
```

---

## Limitazioni note

- **Nessun internet sul Raspberry**: non impatta la cattura (rpicam-still è locale)
- **1 GB RAM Raspberry**: il processo di cattura è leggero (~20MB), nessun problema
- **Latenza SSH**: ~100-200ms per comando, trascurabile rispetto ai tempi di cattura
- **Modello text-only per task puri**: se `vcap_frames=0`, MI50 usa solo output seriale (più veloce)
