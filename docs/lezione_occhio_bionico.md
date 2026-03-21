# Lezione: L'Occhio Bionico — Perché e Come

**Data**: 2026-03-21
**Sessione**: Esperimento visivo prima del terzo run muretto

---

## 1. Il Problema Originale: MI50 non vedeva

### Cosa succedeva

All'inizio del progetto la valutazione visiva funzionava così:

```
frame JPEG → MI50-vision (Qwen3.5-9B multimodal) → {"success": true/false}
```

MI50 riceveva le foto raw del display OLED (640x480) e doveva giudicare se il programma funzionava.

**Problema**: falsi negativi sistematici.

Nella sessione del 2026-03-20 (lezione_muretto.md), MI50 restituiva `success: false` anche quando il display era acceso e animato correttamente. La causa era semplice ma difficile da diagnosticare: **lo sfondo ambientale**.

```
frame originale 640x480:
  - 80% dell'immagine: sfondo rosa/verde/rosso (ambiente fisico del laboratorio)
  - 20% dell'immagine: il display OLED (minuscolo nell'inquadratura)
```

MI50-vision vedeva un'immagine dominata da colori ambientali e concludeva che il display era scuro o non funzionante. Con sfondo rosa → "pixel rosas en fondo" → conclusione: display non attivo.

### Il fix temporaneo (crop + contrasto)

La prima risposta fu preprocessing:

```python
# _preprocess_frames() in evaluator.py
crop = img.crop((mx, my, w - mx, h - my))  # crop 60% centrale
up = crop.resize((cw*2, ch*2), Image.LANCZOS)  # upscale 2x
up = ImageEnhance.Contrast(up).enhance(2.0)     # +contrasto
```

Migliorava la situazione ma non risolveva strutturalmente. Lo sfondo ambientale era ancora presente nel crop, e MI50 continuava a essere influenzato dal colore dominante dell'ambiente.

---

## 2. La Diagnosi: Perché MI50-vision Fallisce Sugli OLED

Il problema non era MI50 in sé — era l'**approccio architetturale**:

| Problema | Impatto |
|----------|---------|
| Il display OLED occupa ≤20% del frame | MI50 vede l'ambiente, non il display |
| OLED ha sfondo nero naturale | Qualsiasi colore ambientale dominante confonde la visione |
| MI50 è multimodal ma non calibrata per pixel bianchi su nero | Percepisce "schermo scuro" dal contesto globale |
| MI50 impiega 5-10 minuti per risposta | Troppo lento per iterare velocemente |

La domanda corretta non era "come migliorare MI50?" ma **"abbiamo davvero bisogno che MI50 veda le immagini?"**.

---

## 3. L'Intuizione: Separare "Vedere" da "Giudicare"

Lele ha formulato l'idea chiave:

> "la webcam dovrebbe avere dei parametri da ritoccare tipo bilanciamento del bianco, contrasti, rilevazione dei bordi... mettendo insieme le cose e facendo analizzare diversi tipi della stessa immagine le cose cambiano... questo tipo di analisi forse potrebbe farlo la M40... potrebbe essere la M40 a vedere e descrivere a MI50 e valutare se ciò che vede è ciò che gli è stato descritto che dovrebbe apparire?"

L'insight cruciale: **separare il vedere (Python deterministic) dal giudicare (LLM)**:

```
Frame → Python/PIL (deterministico) → Descrizione testuale → M40 (giudice) → True/False
```

Invece di chiedere a un LLM di "guardare" un'immagine dominata dall'ambiente, facciamo fare a Python ciò che sa fare meglio: **contare pixel bianchi su sfondo nero**.

---

## 4. L'Implementazione: Pipeline a 3 Strati

### Strato 1: Cattura Ottimizzata (grab_tool.py)

Prima ancora dell'analisi, abbiamo ottimizzato la cattura camera con parametri specifici per OLED:

```python
cmd = [
    "rpicam-still", "-o", path, "--nopreview", "--immediate",
    "--width", "640", "--height", "480", "-q", "75",
    "--awbgains", "2.2,1.8",   # Bilanciamento bianco manuale (no auto-AWB)
    "--contrast", "1.8",        # Contrasto aumentato: pixel OLED più netti
    "--sharpness", "2.0",       # Bordi pixel più definiti
    "--ev", "-0.5",             # EV negativo: evita sovraesposizione OLED brillante
]
```

**Perché awbgains manuali?** L'auto-AWB calibra sulla luce ambientale (rossa/verde/colorata) e tende a normalizzare tutto verso grigi. Con guadagni manuali (2.2 rosso, 1.8 blu) otteniamo colori più stabili e i pixel OLED bianchi rimangono bianchi.

**Risultato**: le tre palline sono chiaramente visibili anche con sfondo rosso dietro al display.

### Strato 2: Analisi Pixel Deterministica (evaluator.py)

```python
def _analyze_frame_pixels(img_gray) -> dict:
    arr = np.array(img_gray)
    binary = (arr > 180).astype(np.uint8)  # threshold: pixel OLED bianchi

    # Scan per righe: trova segmenti contigui (blob)
    for y in range(0, h, 4):
        row = binary[y]
        # ... trova inizio/fine di ogni sequenza di pixel bianchi
        blobs.append({"x": bstart, "y": y, "w": blen})

    # Classifica blob per larghezza:
    small_blobs  = [b for b in blobs if b["w"] <= 10]   # palline candidate
    medium_blobs = [b for b in blobs if 10 < b["w"] <= 35]  # mattoncini candidati
    large_blobs  = [b for b in blobs if b["w"] > 35]     # rumore/ambiente
```

**La chiave del threshold 180**: il preprocessing applica `ImageEnhance.Contrast(gray).enhance(3.0)` prima del threshold. Un pixel grigio ambientale a valore 80 → dopo 3x contrasto → ~180. Ma i pixel OLED bianchi (255) → 255. Il threshold a 180 separa nettamente OLED da ambiente.

**Test su casi estremi** (eseguiti durante questa sessione):

| Condizione | white_ratio | blob_piccoli | blob_medi | Risultato |
|-----------|-------------|--------------|-----------|-----------|
| Display OFF (immagine nera) | 0.0% | 0 | 0 | success=False immediato |
| Sfondo casuale (grigio 80-120) | ~0.0% | 0 | 0 | success=False |
| Display OLED attivo (ambiente reale) | ~24% | 10-12 | 31-38 | success=True |

Il 24% di white_ratio con display reale sembra alto, ma deriva dai riflessi ambientali + luce camera sul frame completo. Il **discriminante robusto** non è il ratio assoluto ma la combinazione:
- `blob_piccoli > 2` → oggetti piccoli (palline) presenti
- `blob_medi > 2` → strutture medie (mattoncini) presenti
- `animation=True` → il programma sta girando

### Strato 3: M40 come Giudice Testuale

M40 (il modello veloce per il codice) riceve una descrizione testuale strutturata e giudica:

```
Frame 1: pixel_bianchi=26876 (24.3%), zona_sinistra=16971px, zona_destra=9905px,
blob_piccoli(≤10px, palline candidate)=10, blob_medi(10-35px, mattoncini candidati)=37,
blob_grandi=82, colonne_attive=325, righe_attive=269
Frame 2: ...
Animazione rilevata: SÌ
```

M40 risponde in JSON:
```json
{"success": true, "reason": "L'animazione è presente, il white_ratio è adeguato e il numero di blob piccoli varia tra i frame, suggerendo movimento. Blob medi coerenti con mattoncini. Blob_grandi sono riflessi ambientali."}
```

**Vantaggi rispetto a MI50-vision**:
- **Velocità**: M40 risponde in ~3 secondi vs 5-10 minuti di MI50
- **Robustezza ambientale**: riceve la descrizione dei pixel OLED, non l'immagine grezza
- **Trasparenza**: il ragionamento è leggibile e debuggabile
- **Costo VRAM**: M40 usa 8GB su GPU dedicata, non occupa MI50

---

## 5. La Scoperta Critica: Il Seriale Batte Tutto

Durante i test, è emerso un limite fondamentale della pixel analysis:

**La pixel analysis NON può distinguere fisica corretta da fisica rotta.**

Esempio concreto dalla sessione muretto2:
- Frames con bug (double vy inversion): blob_piccoli=13-16, animation=True → M40 dice success=True
- Frames corretti (fix manuale): blob_piccoli=10-12, animation=True → M40 dice success=True

I due casi sono **indistinguibili dalla pixel analysis** perché:
- In entrambi il display è acceso e animato
- I blob ci sono in entrambi i casi
- La fisica rotta non si vede nelle statistiche aggregate

**La soluzione**: il seriale è il vero verificatore funzionale.

```
HIT → una pallina ha colpito un mattoncino
BREAK → tutti i mattoncini sono stati distrutti
REGEN → nuovi mattoncini sono apparsi
```

Questi eventi confermano non solo che il display è attivo, ma che la **logica** funziona.

Da questa osservazione è nata la **serial-first priority** nel pipeline:

```python
# Step 0: serial events fast-path (priorità massima)
if expected_events and serial_output and serial_output.strip():
    matched = [ev for ev in expected_events if ev in serial_output]
    if len(matched) >= max(1, len(expected_events) // 2):
        return {
            "success": True,
            "reason": f"Serial output contiene eventi attesi: {matched}. [serial-first]",
            "pipeline": "serial-first",
        }
```

**Se gli eventi seriali sono presenti → successo immediato, zero visual analysis.**

---

## 6. Il Pipeline Finale

```
┌─────────────────────────────────────────────────────────────┐
│           evaluate_visual_opencv()                          │
│                                                             │
│  Step 0: Serial events?                                     │
│    → HIT/BREAK trovati nel seriale → success=True [0.1s]   │
│         ↓ no serial events                                  │
│                                                             │
│  Step 1: Pixel analysis (PIL/numpy)                         │
│    → _build_pixel_description() → stats per ogni frame     │
│    → _frames_differ() → animation detected?                 │
│    → Se tutti i frame hanno "errore analisi" → skip a MI50  │
│         ↓                                                   │
│                                                             │
│  Step 2: M40 VisualJudge (~3s)                              │
│    → Riceve descrizione testuale pixel                      │
│    → Giudica vs comportamento atteso                        │
│    → success=true → return [3s totale]                     │
│         ↓ success=false                                     │
│                                                             │
│  Step 3: MI50-vision fallback (~5-10 min)                   │
│    → 3 versioni immagine (crop + threshold + edge)          │
│    → MI50 guarda le immagini preprocessate                  │
│    → Risposta definitiva                                    │
└─────────────────────────────────────────────────────────────┘
```

**Tempi tipici per task muretto:**
- Serial-first: ~0.1s (solo string search)
- opencv+M40: ~3-5s (PIL analysis + M40 generate)
- MI50-vision fallback: ~5-10 min (solo se M40 fallisce)

---

## 7. Limiti Identificati e Roadmap

### Limiti attuali

1. **Blob classification è approssimativa**: il blob scan per righe (ogni 4 righe) può perdere strutture verticali. Un rettangolo verticale alto 8px potrebbe non essere visto se il campionamento cade fuori.

2. **white_ratio assoluto non affidabile**: il 24% di white pixels include riflessi ambientali. Non usare il ratio come soglia assoluta — usare sempre in combinazione con blob stats.

3. **Camera position dipendente**: le soglie blob (≤10px, 10-35px, >35px) dipendono dalla distanza camera-display. Se la camera viene spostata, le soglie vanno ricalibrate.

4. **Display parzialmente visibile**: se il display è angolato o parzialmente coperto, i blob cambiano dimensione e la classificazione potrebbe sbagliare.

### Miglioramenti futuri

- **Calibrazione automatica**: un frame di riferimento iniziale (display con pattern noto) permetterebbe di calibrare automaticamente le soglie blob
- **Blob detection 2D**: invece di scan per righe (1D), usare connected components PIL per trovare blob 2D reali
- **Coordinate blob**: sapere dove si trovano i blob (non solo quanti) permetterebbe di verificare la posizione degli elementi (paddle in basso, mattoncini in alto)
- **Confronto inter-frame per posizione**: tracciare la posizione delle palline frame-per-frame confermerebbe il movimento reale

---

## 8. Risultato della Sessione

Alla fine degli esperimenti, il pipeline è stato testato con successo su 3 scenari:

```
TEST A (visual only, serial vuoto):
  success=True, pipeline=opencv+m40
  "L'animazione è presente, blob_piccoli varia tra frame, suggerendo movimento"

TEST B (serial-first, eventi HIT presenti):
  success=True, pipeline=serial-first
  "Serial output contiene eventi attesi: ['HIT']. [serial-first]"

TEST C (percorsi frame errati):
  → Guard "errore analisi" attivato
  → MI50-vision fallback chiamato direttamente
  → success=True, pipeline=mi50-vision-fallback
```

L'occhio bionico funziona. Il prossimo step è il terzo run del muretto con il task completo (tutte le correzioni già incluse) per verificare l'autonomia del programmatore con la nuova pipeline di valutazione.

---

## Appendice: Struttura file modificati

| File | Modifica |
|------|---------|
| `agent/grab_tool.py` | Parametri rpicam-still ottimizzati per OLED |
| `agent/evaluator.py` | Pipeline completa: serial-first + PIL pixel analysis + M40 judge + MI50 fallback |
| `agent/tool_agent.py` | Upload retry loop (max 2) + serial-first in _evaluate_visual() |

```python
# grab_tool.py — parametri chiave
"--awbgains", "2.2,1.8"  # bilanciamento bianco manuale
"--contrast", "1.8"       # contrasto OLED
"--sharpness", "2.0"      # bordi pixel
"--ev", "-0.5"            # no sovraesposizione

# evaluator.py — soglie pixel (dipendenti da distanza camera)
blob_piccoli = w <= 10   # palline (~3-8px su OLED a ~20cm)
blob_medi    = 10 < w <= 35  # mattoncini (~20-30px)
blob_grandi  = w > 35    # rumore ambientale (ignora)

# discriminante finale
display_ok = animation_detected AND blob_piccoli > 2 AND blob_medi > 2
```
