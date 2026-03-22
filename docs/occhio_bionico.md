# Occhio Bionico — Documentazione

> Progetto: `agent/occhio/`
> Avviato: 2026-03-22
> Stato: implementato, test sintetici ok

---

## Cos'è

L'**Occhio Bionico** è il sistema visivo del programmatore di Arduini.

Prima c'era una singola pipeline monolitica (`evaluate_visual`) che cercava di fare tutto:
cattura, analisi, giudizio. Un'unica configurazione camera per tutti i task, nessun
diff temporale, blob detection senza coordinate.

Ora ci sono **7 tool componibili**, ognuno con uno scopo preciso. MI50 sceglie quali
usare in base al task e li combina come vuole — esattamente come fa con i tool Arduino.

---

## Architettura

```
agent/occhio/
├── __init__.py       ← esporta i 7 tool pubblici
├── _common.py        ← costanti, preset, load/save calibrazione
├── calibrate.py      ← calibrate_eye()
├── capture.py        ← capture_frames(), check_display_on()
├── analyze.py        ← detect_motion(), count_objects()
├── read.py           ← read_text()   [MI50-vision isolata]
└── describe.py       ← describe_scene()  [M40 + MI50 fallback]

workspace/
└── eye_calibration.json   ← scritto da calibrate_eye(), letto da tutti gli altri
```

### Separazione dei ruoli

| Componente | Ruolo |
|------------|-------|
| **PIL + numpy + scipy** | analisi pixel locale (veloce, deterministica) |
| **M40** (Gemma 3 12B) | VisualJudge: giudica la descrizione testuale della scena |
| **MI50** (Qwen3.5-9B) | vision fallback (lento, immagini reali) + calibrazione |
| **Raspberry Pi** | cattura frame via rpicam-still (CSI camera) |

**M40 non vede mai immagini** — riceve descrizioni testuali strutturate generate dalla
pixel analysis PIL. È veloce (~3-5 secondi) e non richiede GPU per la visione.

**MI50** viene coinvolto solo in due casi:
1. `describe_scene` con confidence M40 < 0.6 (fallback)
2. `read_text` (OCR — l'unico tool che richiede vision multimodale)

---

## Preset camera

Cinque configurazioni per condizioni diverse:

| Preset | EV | Contrasto | Quando |
|--------|----|-----------|--------|
| `standard` | -0.5 | 1.8 | Default, luci accese |
| `dark` | 0.0 | 2.5 | Stanza buia, OLED unica fonte di luce |
| `bright` | -1.5 | 1.5 | Luce intensa, EV negativo per non saturare |
| `oled_only` | -0.5 | 3.0 | Max contrasto, isola pixel OLED |
| `high_contrast` | -1.0 | 2.2 | Buon bilanciamento per LED e testo |

Il preset vincente viene salvato in `workspace/eye_calibration.json` e usato
automaticamente da tutti i tool successivi.

---

## Tool — API di riferimento

### `calibrate_eye(target)` — Calibrazione camera

```python
from agent.occhio import calibrate_eye

result = calibrate_eye(target="oled")
# target: "oled" | "led" | "general"
```

**Output:**
```json
{
  "best_preset": "bright",
  "target": "oled",
  "calibrated_at": "2026-03-22T18:00:00",
  "scores": {"standard": 0.42, "bright": 0.91, "dark": 0.23, "oled_only": 0.78, "high_contrast": 0.55},
  "white_ratio_at_calibration": 0.18,
  "results": { "...": "..." }
}
```

**Quando chiamarla:** una volta per sessione (PREFLIGHT STEP 8) o dopo cambio setup fisico.

**Scoring per target:**
- `oled`: premia `white_ratio` 0.05–0.30, blob_count > 2, penalizza saturazione e rumore
- `led`: premia range dinamico ampio (LED puntiforme su sfondo scuro)
- `general`: bilancia contrasto e rumore

---

### `capture_frames(n, interval_ms)` — Cattura sequenza temporale

```python
from agent.occhio import capture_frames

paths = capture_frames(n=3, interval_ms=1000)
# → ["/tmp/grab_local_.../frame_001.jpg", ...]
```

**Caratteristiche chiave:**
- Il timing è gestito **interamente da questo tool** — MI50 e M40 non sono coinvolti
  tra una cattura e l'altra (sono troppo lenti: secondi di inferenza vs ms di intervallo)
- Usa automaticamente il preset da `eye_calibration.json`
- **Cattura adattiva**: se il primo frame ha `white_ratio > 0.60` (sovraesposto) o
  `< 0.001` (tutto buio), ritenta con preset alternativo (1 solo retry)

**Casi d'uso tipici:**
```python
capture_frames(3, 1000)   # 3 secondi di osservazione
capture_frames(5, 500)    # animazione veloce, 2.5 secondi
capture_frames(2, 3000)   # verifica se qualcosa cambia in 3 secondi
```

---

### `check_display_on()` — Display attivo?

```python
from agent.occhio import check_display_on

result = check_display_on()
```

**Output:**
```json
{"on": true, "white_ratio": 0.18, "preset_used": "bright"}
```

**Logica:** `white_ratio > 0.003` → display ON. 1 frame, ~3 secondi totali.

**Quando usarlo:** sempre come primo check prima di qualsiasi analisi più costosa.
Se il display è OFF, inutile fare blob detection o motion analysis.

---

### `detect_motion(frame_paths)` — Rileva movimento

```python
from agent.occhio import detect_motion

result = detect_motion(frame_paths)
```

**Output:**
```json
{
  "motion_detected": true,
  "mean_diff": 8.3,
  "centroid_displacement": 12.4,
  "confidence": "high",
  "frames_analyzed": 3
}
```

**Perché due metriche?**

- `mean_diff`: differenza pixel media inter-frame. Alta anche con flickering o riflessi ambientali.
- `centroid_displacement`: spostamento medio dei centroidi blob tra frame 0 e frame N.
  Conferma che gli stessi oggetti si sono *fisicamente spostati* — non è rumore.

Confidence:
- `high`: entrambe le metriche concordano (diff > 2.0 **e** displacement > 3.0)
- `medium`: solo una delle due
- `low`: nessuna delle due

---

### `count_objects(frame_paths)` — Conta e localizza oggetti

```python
from agent.occhio import count_objects

result = count_objects(frame_paths)
```

**Output:**
```json
{
  "total": 5,
  "dots":     [{"cx": 45, "cy": 12, "area": 8}, {"cx": 78, "cy": 34, "area": 4}],
  "segments": [{"cx": 64, "cy": 48, "area": 120}],
  "blocks": 1,
  "description": "2 punti piccoli (alto-sinistra, centro-destra); 1 segmento (centro-centro); 1 blocco grande (artefatti ambientali, non contati)"
}
```

**Categorizzazione per area (pixel):**
- `dot` ≤ 16px — pixel singoli, 2×2, 4×4 — tipico OLED (boids, pixel sparsi)
- `segment` 17–200px — segmenti corpo snake, palline piccole, caratteri testo
- `block` > 200px — riflessi ambientali, grandi forme — **non contati nel `total`**

**Implementazione:**
- Crop centrale 380×288px per escludere bordi webcam
- `scipy.ndimage.label()` per regioni connesse 2D + fallback BFS se scipy assente
- Coordinate centroide (cx, cy) per ogni blob

---

### `read_text(frame_paths)` — Leggi testo sul display

```python
from agent.occhio import read_text

result = read_text(frame_paths)
```

**Output:**
```json
{"text_found": true, "text": "SCORE: 42", "confidence": "medium"}
```

**Implementazione:**
1. Preprocessing PIL: crop centrale, boost contrasto ×3, threshold B&W, 2× upscale
2. MI50-vision con prompt dedicato: `"Leggi SOLO il testo visibile. Non descrivere altro."`
3. Context **isolato** — non tocca il context principale MI50

**Quando usarlo:** task con OLED che mostra score, messaggi, menu.
**Non usarlo** per task grafici puri (boids, palline) — lento e inutile.

---

### `describe_scene(frame_paths, goal)` — Descrizione libera guidata

```python
from agent.occhio import describe_scene

result = describe_scene(
    frame_paths=paths,
    goal="verifica che ci siano almeno 5 palline che si muovono"
)
```

**Output:**
```json
{
  "description":   "OBIETTIVO: ... \nOGGETTI: 5 dots ...\nMOVIMENTO: RILEVATO ...",
  "success_hint":  true,
  "confidence":    0.82,
  "reason":        "Rilevati 5 punti in movimento, coerente con task",
  "pipeline_used": "m40",
  "objects":       {...},
  "motion":        {...}
}
```

**Pipeline interna:**
```
count_objects(frame_paths)
    ↓
detect_motion(frame_paths)      [solo se > 1 frame]
    ↓
_build_text_description()       [testo strutturato per M40]
    ↓
M40 VisualJudge                 [giudica testo, non immagini — veloce]
    ↓ se confidence < 0.6
MI50-vision fallback            [immagini reali — lento]
```

**È il tool più flessibile ma anche il più lento.** Usarlo come ultimo step di valutazione,
non come primo check.

---

## Composizione tipica

### Task "5 boids su OLED"

```python
# 1. Check rapido
status = check_display_on()
if not status["on"]:
    # display spento — non procedere
    ...

# 2. Cattura sequenza
frames = capture_frames(n=3, interval_ms=1000)

# 3. Ci sono oggetti?
objects = count_objects(frames)
# → {"total": 5, "dots": [...], ...}

# 4. Si muovono?
motion = detect_motion(frames)
# → {"motion_detected": true, "confidence": "high"}

# 5. Valutazione finale
verdict = describe_scene(
    frame_paths=frames,
    goal="almeno 5 punti luminosi in movimento autonomo su OLED"
)
# → {"success_hint": true, "confidence": 0.87, "pipeline_used": "m40"}
```

### Task "display con score"

```python
frames = capture_frames(n=1, interval_ms=0)
text   = read_text(frames)
# → {"text_found": true, "text": "SCORE: 42", "confidence": "high"}
```

---

## Integrazione con pipeline esistente

`evaluate_visual` rimane invariato come **wrapper di compatibilità** per i task che
usano il flusso legacy `grab_frames → evaluate_visual`.

I nuovi tool sono alternativi, non sostitutivi:

```
FLUSSO LEGACY:    grab_frames → evaluate_visual
FLUSSO MODULARE:  check_display_on → capture_frames → count_objects → describe_scene
```

MI50 sceglie quale flusso usare in base al task. Il system prompt di `tool_agent.py`
presenta entrambe le opzioni.

---

## Punti deboli e mitigazioni

| Rischio | Mitigazione |
|---------|-------------|
| scipy assente | BFS fallback in `analyze.py` |
| Blob 2D lento | Crop 380×288 prima, scipy label < 50ms |
| `mean_diff` alto = rumore (non movimento) | `centroid_displacement` come secondo check |
| `read_text` lento (MI50-vision) | Context isolato, non tocca main context |
| False positive con `describe_scene` | confidence < 0.6 → MI50-vision fallback |
| calibrate_eye aggiunge ~10s al preflight | Fatto una sola volta per sessione |
| Cattura adattiva non perfetta | 1 solo retry — peggio del preset originale viene scartato |

---

## File di calibrazione

`workspace/eye_calibration.json`:

```json
{
  "preset": "bright",
  "target": "oled",
  "calibrated_at": "2026-03-22T18:00:00",
  "scores": {
    "standard": 0.42,
    "bright":   0.91,
    "dark":     0.23,
    "oled_only": 0.78,
    "high_contrast": 0.55
  },
  "white_ratio_at_calibration": 0.18
}
```

---

## Note di progettazione

- **OpenCV lato Pi**: scartato — installazione pesante, nessun vantaggio reale rispetto a PIL lato server
- **Vision server lato Pi**: scartato — complessità deployment, latenza SCP accettabile
- **M40 per timing tra catture**: impossibile — M40 ha ~15-20 tok/sec, non può orchestrare intervalli di ms
- **I tool visivi NON sostituiscono il serial-first** — il serial output rimane la via più veloce e affidabile
- **Context swap MI50**: già corretto nell'architettura attuale — `read_text` e `describe_scene`
  usano context isolati che non inquinano il loop principale di MI50
