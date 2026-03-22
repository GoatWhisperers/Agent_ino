# Progetto Vision Tools — Occhio Bionico Modulare

> Avviato: 2026-03-22
> Stato: design completato, implementazione da fare

---

## Motivazione

Il sistema attuale ha un'unica pipeline visiva monolitica (`evaluate_visual`) che tenta
di fare tutto in un colpo: cattura, analisi pixel, giudizio M40, fallback MI50.
Il risultato è fragile: un'unica configurazione camera per tutti i task, nessun diff
temporale reale, blob detection senza coordinate, nessuna calibrazione adattiva.

I vision tool devono essere **componibili e per scopo**, come i tool Arduino:
MI50 sceglie quale usare in base al task, li combina, interpreta i risultati.

---

## Tool di visione pianificati

### `calibrate_eye(target)` — Calibrazione camera

**Scopo**: trovare i parametri camera ottimali per il setup fisico corrente.
**Input**: `target = "oled" | "led" | "general"`
**Output**: preset ottimale + score per ogni preset, salvato in `workspace/eye_calibration.json`

**Funzionamento**:
1. Cattura 1 frame per ogni preset (`standard`, `dark`, `bright`, `oled_only`, `high_contrast`)
2. Calcola quality score per target:
   - `oled`: `white_ratio` 0.05–0.40, `blob_count > 2`, non saturato
   - `led`: range brightness ampio, risposta ai cambiamenti
   - `general`: bilanciamento contrasto/rumore
3. Salva preset vincente + tutti gli score
4. Ritorna descrizione di ogni tentativo (MI50 può sovrascrivere la scelta automatica)

**Quando chiamarlo**: una volta per sessione nel PREFLIGHT (STEP 8), o dopo cambio setup fisico.

**File**: `workspace/eye_calibration.json`
```json
{
  "preset": "bright",
  "target": "oled",
  "calibrated_at": "2026-03-22T18:00:00",
  "scores": {"standard": 0.72, "bright": 0.91, "dark": 0.23},
  "white_ratio_at_calibration": 0.18
}
```

---

### `capture_frames(n, interval_ms)` — Cattura sequenza temporale

**Scopo**: scattare N frame a distanza fissa nel tempo. Solo cattura, nessuna analisi.
**Input**: `n=3`, `interval_ms=1000`
**Output**: lista path JPEG locali

**Note critiche**:
- Il timing è gestito **interamente dal tool**, non da MI50 o M40
- M40 è troppo lento per orchestrare il timing tra catture (secondi di inferenza vs ms di intervallo)
- Usa automaticamente il preset salvato dalla calibrazione
- Cattura adattiva: se il primo frame ha `white_ratio > 0.60` (sovraesposto) o
  `white_ratio < 0.001` (tutto buio), ritenta con preset alternativo (1 solo retry)

**Casi d'uso**:
- `capture_frames(3, 1000)` → 3 secondi di osservazione, poi analisi
- `capture_frames(5, 500)` → animazione veloce, 2.5 secondi
- `capture_frames(2, 3000)` → verifica se qualcosa cambia in 3 secondi

---

### `check_display_on()` — Display attivo?

**Scopo**: verifica rapida se il display mostra qualcosa. Binary check.
**Output**: `{"on": true/false, "white_ratio": 0.18, "preset_used": "bright"}`

**Quando usarlo**: prima di qualsiasi altra analisi visiva. Se il display è off,
inutile procedere con blob detection o motion analysis.

**Implementazione**: 1 frame, `white_ratio > 0.003` → on.

---

### `detect_motion(frame_paths)` — Rileva movimento

**Scopo**: c'è qualcosa che si muove tra i frame?
**Input**: path di frame già catturati (da `capture_frames`)
**Output**:
```json
{
  "motion_detected": true,
  "mean_diff": 8.3,
  "centroid_displacement": 12.4,
  "confidence": "high"
}
```

**Implementazione**:
- Diff pixel inter-frame (numpy `absdiff`)
- `mean_diff > 2.0` → motion detected
- `centroid_displacement`: spostamento medio dei centroidi blob tra frame 0 e frame N
  (distingue "molti pixel diversi" da "gli stessi oggetti si sono spostati")

**Perché centroid_displacement**: `mean_diff` alto può essere rumore (flickering display,
riflessi ambientali). Il displacement dei centroidi conferma che gli stessi oggetti
si sono fisicamente spostati.

---

### `count_objects(frame_paths)` — Conta e localizza oggetti

**Scopo**: quanti oggetti distinti ci sono sul display e dove?
**Input**: path frame
**Output**:
```json
{
  "total": 5,
  "dots": [{"cx": 45, "cy": 12, "area": 8}, {"cx": 78, "cy": 34, "area": 4}],
  "segments": [{"cx": 64, "cy": 48, "area": 120}],
  "blocks": 1,
  "description": "2 piccoli punti in alto, 1 segmento al centro, 1 blocco grande (rumore/ambiente)"
}
```

**Implementazione**: blob 2D con `scipy.ndimage.label()` + fallback BFS.
Categorizzazione per area:
- `dot`: ≤ 16px (pixel singoli, 2×2, 4×4 — tipico OLED)
- `segment`: 17–200px (segmenti di corpo snake, palline piccole)
- `block`: > 200px (riflessi ambientali, grandi forme geometriche)

**Filtro rumore**: i `block` vengono segnalati ma non contati come oggetti "veri" —
quasi sempre sono artefatti ambientali.

---

### `read_text(frame_paths)` — Leggi testo sul display

**Scopo**: c'è testo leggibile? Cosa dice?
**Input**: path frame
**Output**: `{"text_found": true, "text": "SCORE: 42", "confidence": "medium"}`

**Implementazione**:
- Preprocessing: contrast boost + threshold + crop display area
- MI50-vision con prompt dedicato: "Leggi SOLO il testo visibile. Non descrivere altro."
- Context **isolato** — non inquina il context principale di MI50

**Quando usarlo**: task con OLED che mostra score, messaggi, menu.
Non chiamarlo per task puramente grafici (palline, boids) — inutile e lento.

---

### `describe_scene(frame_paths, goal)` — Descrizione libera guidata

**Scopo**: descrizione generale di cosa vedi, guidata da un obiettivo.
**Input**: frame paths + goal string (es. "verifica che ci siano almeno 5 palline che si muovono")
**Output**: `{"description": "...", "success_hint": true/false, "confidence": "low/medium/high"}`

**Implementazione**:
1. `count_objects` → blob stats
2. `detect_motion` → motion stats
3. Descrizione testuale strutturata → M40 VisualJudge (veloce, testo)
4. Se M40 incerto (confidence < 0.6) → MI50-vision fallback (lento, immagini)

**È il tool più flessibile** ma anche il più lento. Usarlo come ultimo resort,
non come prima scelta.

---

## Architettura

```
workspace/eye_calibration.json     ← salvato da calibrate_eye()
         ↑
agent/occhio/
  __init__.py
  calibrate.py    ← calibrate_eye()
  capture.py      ← capture_frames() + logica adattiva
  analyze.py      ← detect_motion(), count_objects(), check_display_on()
  read.py         ← read_text() via MI50-vision isolata
  describe.py     ← describe_scene() = analyze + M40 + MI50 fallback
```

Tutti i tool vengono registrati in `tool_agent.py` come tool MI50 chiamabili nel ReAct loop.

---

## Integrazione con pipeline esistente

`evaluate_visual` attuale rimane invariato come **wrapper di compatibilità** —
chiama internamente `capture_frames` + `describe_scene` se i nuovi tool sono disponibili,
altrimenti fallback al codice precedente.

I nuovi tool vengono esposti a MI50 nel system prompt come alternative più precise:

```
TOOL VISIVI DISPONIBILI:
- calibrate_eye(target)           → calibrazione camera (solo a inizio sessione)
- capture_frames(n, interval_ms)  → cattura N frame a distanza fissa
- check_display_on()              → display attivo? (check rapido)
- detect_motion(frame_paths)      → movimento rilevato?
- count_objects(frame_paths)      → quanti oggetti e dove?
- read_text(frame_paths)          → leggi testo sul display (MI50-vision, lento)
- describe_scene(frame_paths, goal) → descrizione libera guidata
```

MI50 può comporre i tool:
```
capture_frames(5, 1000) → detect_motion → count_objects → describe_scene
```
oppure usarne solo uno se il serial-first ha già risposto.

---

## Punti deboli identificati (analisi pre-implementazione)

| # | Rischio | Mitigazione |
|---|---------|-------------|
| scipy non nel venv | Fallback a scan 1D già presente |
| Blob 2D lento | Crop prima (380×288px), scipy label < 50ms |
| False match centroid displacement | Solo hint, non decisore unico |
| OpenCV sul Pi | Non necessario — PIL lato server sufficiente |
| Camera settling tra preset | `sleep(0.5)` dopo cambio preset |
| M40 non usa coordinate blob | Istruzione esplicita nel system prompt |
| read_text lento (MI50-vision) | Context isolato, non inquina run principale |
| calibrate_eye aggiunge 8-16s al preflight | Fatto una sola volta per sessione |

---

## Piano implementazione (ordine priorità)

1. **`capture_frames` con timing interno e cattura adattiva** — base di tutto
2. **`count_objects` con blob 2D + coordinate** — massimo impatto su qualità giudizio
3. **`detect_motion` con centroid displacement** — distingue animato da bloccato
4. **`calibrate_eye`** — preflight STEP 8
5. **`check_display_on`** — semplice, 30 min di lavoro
6. **`describe_scene`** — integra i precedenti + M40 + MI50 fallback
7. **`read_text`** — ultimo, dipende da MI50-vision isolata

---

## Note

- OpenCV lato Pi: scartato (installazione pesante, nessun vantaggio reale rispetto a PIL lato server)
- Vision server lato Pi: scartato (complessità deployment, latenza SCP accettabile)
- Context swap MI50: già isolato correttamente nell'architettura attuale
- I tool visivi NON sostituiscono il serial-first — quello rimane la via più veloce e affidabile
