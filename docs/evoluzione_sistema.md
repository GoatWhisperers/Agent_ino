# Evoluzione del Sistema — Programmatore di Arduini

> Aggiornato: 2026-03-22

Due fronti paralleli di evoluzione: il **sistema** (pipeline, robustezza, architettura) e la **knowledge base** (lessons che guidano la generazione di codice).

---

## FRONTE 1: Evoluzione del Sistema

### Architettura a strati — come è cresciuta

Il sistema è partito da un loop semplice `generate → compile → upload → eval` e si è evoluto in una pipeline con:

```
MI50 (planning)     →  KB lessons iniettate upfront
M40 (code gen)      →  fix proattivi prima di compile
arduino-cli         →  fix errori noti prima di passare a M40
PlatformIO (Pi)     →  upload con retry + kill stuck
valutazione         →  serial-first → PIL → M40 judge → MI50-vision
save_to_kb          →  SQLite + ChromaDB auto-sync
```

Ogni layer ha acquisito difese autonome che evitano di dover fare rifare il giro completo.

---

### Compiler.py — Fix proattivi accumulati

Il compiler è diventato il primo scudo: corregge senza chiedere prima ancora che arduino-cli provi a compilare.

| Funzione | Bug corretto | Quando si attiva |
|---------|-------------|-----------------|
| `fix_italian_pseudocode()` | M40 genera pseudocodice italiano senza `//` | sempre (proattivo) |
| `fix_known_includes()` | include sbagliati (SSD1306.h, Adafruit_GFX::WHITE, ecc.) | sempre (proattivo) |
| `_fix_uint8_grid_pointer()` | `uint8_t* grid` invece di `uint8_t grid[][16]` | proattivo + error-triggered |
| `_fix_display_userfunc_calls()` | funzioni utente chiamate come `display.myFunc()` | error-triggered |
| `_fix_getTextBounds_call()` | `textWidth()` → `getTextBounds()` con tipi corretti | error-triggered |
| `_fix_dist_function()` | `dist()` non esiste in Arduino → inietta implementazione | error-triggered |
| `_fix_setupPhysics_call()` | `setupPhysics()` inventato da M40 → inlined in setup() | error-triggered |
| `_fix_drawCircle_float()` | `drawCircle(float x, float y, ...)` → cast a int | error-triggered |
| `_fix_setPixel_to_drawPixel()` | `setPixel()` non esiste → `drawPixel()` | error-triggered |

**Principio**: ogni volta che un bug si ripete due volte, diventa un fix proattivo o error-triggered. Non si aspetta che M40 lo impari.

---

### Generator.py — SYSTEM_FUNCTION come memoria delle regole

`SYSTEM_FUNCTION` è cresciuto da ~5 regole a 20+. È la "memoria a lungo termine" della generazione:

**Regole hardware** (SDA/SCL, rst_pin, I2C addr, colori monocromatici):
- Wire.begin(21,22) sempre esplicito
- Adafruit_SSD1306(W, H, &Wire, -1) — 4° param è rst_pin non addr
- Solo SSD1306_WHITE — nessun colore RGB

**Regole di codice C++ Arduino**:
- Timer: `unsigned long`, mai `int` (overflow a 32s)
- `dist()` non esiste → sqrt(pow(...))
- `display.setPixel()` non esiste → `drawPixel()`
- NON stesso nome per variabile globale e funzione
- drawCircle/fillCircle: x,y,r DEVONO essere int (cast esplicito)

**Regole per fisica/animazione**:
- vx/vy come px/frame (1.5-3.0), non px/sec×dt (porta a movimento immobile)
- Velocità iniziali: verificare vx!=0 e vy!=0 dopo random()
- loop() chiama ESATTAMENTE i tool di alto livello, non le sub-funzioni

**Regole Conway** (accumulate in 3 run):
- bit packing: colonna=x/8, bit=x%8 (mai x%BITMAP_COLS)
- firme: `uint8_t grid[][16]` (mai `uint8_t* grid`)
- swapGrids() UNA SOLA VOLTA per frame, in loop() non in computeNext
- serial timer millis() in loop(), non nella funzione di stampa
- delay(16) in loop() dopo drawGrid() (altrimenti millis() non avanza)
- stable→reinit in loop()

**Regole boids/predatore**:
- predator.id = indice target (0..N-1), mai nextPreyId++ dopo init
- respawnTime per-preda (campo struct), non timer globale condiviso
- respawnPrey(int i) con indice esplicito, non spawnPrey() con nextPreyId
- Serial.println() per terminare ogni riga multi-campo

---

### Tool Agent (tool_agent.py) — Robustezza del ReAct loop

Il loop ReAct ha acquisito meccanismi difensivi a ogni sessione:

| Meccanismo | Problema che risolve | Quando aggiunto |
|-----------|---------------------|----------------|
| `_truncate_to_first_action()` | MI50 run-ahead hallucination (genera più azioni di fila) | sessione 2026-03-11 |
| Guard `_plan_functions` | MI50 ripete plan_functions già fatto | sessione 2026-03-20 |
| `_anchor_uploading` con ISTRUZIONE CRITICA | MI50 in fase upload chiama plan_task | sessione 2026-03-22 |
| `_anchor_done` con eval_result | MI50 in done vede serial spam e conclude FAILED | sessione 2026-03-22 |
| `_serial_summary()` | 40000 righe serial identiche → summary deduplicata | sessione 2026-03-22 |
| Guard `_plan_task` per fasi avanzate | MI50 in fase UPLOADING chiama plan_task (20 min sprecati) | sessione 2026-03-22 |
| Loop detection (×3 stesso tool) | MI50 bloccato in loop → hint forzato + reset | sessione 2026-03-22 |
| Checkpoint write atomico | crash a metà write → checkpoint corrotto | sessione 2026-03-22 |
| `anchor_done` con success esplicito | `{"done":true}` senza success → run FAILED per default | sessione 2026-03-22 |
| Retry automatico `generate_all_functions` | M40 timeout silenzioso → funzione `pending` ma ok:True | sessione 2026-03-21 |
| Stub detection | M40 genera `// TODO` nel codice → avvisa MI50 | sessione 2026-03-22 |
| KB lessons nel patch M40 | M40 patcher non vede lessons KB rilevanti | sessione 2026-03-22 |
| Iterations reali in `save_to_kb` | `sess.compile_errors` non esisteva → learner cieco | sessione 2026-03-22 |

**Pattern ricorrente**: ogni volta che MI50 prende una decisione sbagliata, si aggiunge informazione nell'anchor della fase corrente per evitare che accada di nuovo. Il sistema impara dai propri fallimenti strutturali.

---

### Evaluator — Pipeline visiva stratificata

Partito da: "chiedi a MI50-vision se il display funziona" → spesso falso negativo (sfondo colorato).

Evoluto in pipeline a 4 livelli:
```
Step 0: Serial-first — se serial contiene expected_events → success=True immediato (0.1s)
Step 1: PIL pixel analysis — white_ratio, blob detection, descrizione testuale strutturata
Step 2: M40 VisualJudge — valuta descrizione vs task (testo, no immagini, veloce)
Step 3: MI50-vision fallback — solo se M40 non convince (lento, 5+ min)
```

**Risultato**: il serial è il vero verificatore funzionale. Il visual è un backup per task display-only senza serial pattern.

---

## FRONTE 2: Evoluzione della Knowledge Base

### Struttura KB

Doppio storage: SQLite (fonte di verità) + ChromaDB (ricerca semantica). Fino a sessione 2026-03-22, erano out of sync — ora `add_lesson()` chiama `index_lesson()` automaticamente.

**32 lessons** suddivise in:
- ~12 lessons di configurazione hardware OLED/ESP32 (I2C, pin, addr, colori)
- ~8 lessons di animazione e fisica OLED (vx/vy, bounce, collisioni)
- ~6 lessons Conway (bit packing, swap, serial, compute, delay)
- ~3 lessons Boids/Predatore (timer, respawn, serial output)
- ~3 lessons sistema (M40 backtick, evaluate_visual, visual verification)

### Come le lessons vengono usate

**Tre punti di iniezione** nella pipeline:

```
1. plan_task (KB enrichment)
   _auto_enrich_task() → semantic search → top 5 lessons rilevanti
   → iniettate nel contesto di plan_task + plan_functions
   → MI50 le vede mentre pianifica le funzioni

2. _anchor_compiling (KB per compilazione)
   se ci sono errori → ricerca SQLite con query = task + errori
   → top 2 lessons iniettate nell'anchor
   → MI50 le vede mentre decide se fare patch_code

3. _patch_code (KB per M40 patcher)
   ricerca semantic + fallback SQLite
   → top 3 lessons iniettate nel prompt di patch_code
   → M40 le vede mentre corregge il codice
```

### Ciclo di vita di una lesson

```
Run con bug M40
    ↓
Bug documentato nella lezione (.md) + aggiunto a KB manualmente o via save_to_kb
    ↓
Lesson in SQLite (fonte di verità) → auto-sync a ChromaDB
    ↓
Sessione successiva: _auto_enrich_task() trova la lesson
    ↓
MI50 pianifica funzioni con la regola già presente
    ↓
M40 genera codice corretto (o quasi)
    ↓
Se ancora sbagliato: fix proattivo aggiunto al compiler.py o SYSTEM_FUNCTION
```

**Principio**: le lessons nella KB sono "soft rules" — guidano ma non garantiscono. I fix nel compiler e in SYSTEM_FUNCTION sono "hard rules" — applicati sempre indipendentemente da M40.

### Evoluzione per task

| Task | Lessons generate | Lessons applicate dalla run successiva |
|------|-----------------|---------------------------------------|
| 3 palline (muretto) | Rimbalzo, collisione mattoncino, regenActive, OLED setup | → usate in predatore |
| Predatore Boids v1 | Steering boids, predator.id OOB, timer per-preda | → usate in predatore v2/v3 |
| Conway v1 | Bit packing x/8, swap once per frame, serial millis | → usate in Conway v2 (MI50 le ha viste!) |
| Conway v2 | `uint8_t grid[][16]`, delay(16), stable→reinit | → usate in Conway v3 |
| Conway v3 | Naming conflict (var+func), setPixel→drawPixel | → prossima run |

**Osservazione**: il numero di patch necessarie diminuisce da run a run per lo stesso dominio. Conway v1: ~5 bug M40. Conway v2: 2 bug M40. Conway v3: 2 bug M40 diversi. Nessuno dei bug di v1/v2 si è ripresentato in v3 — le lessons funzionano.

---

## Rapporto tra i due fronti

```
KB lessons (soft, dominio-specifiche)
    ↓
guidano M40 nella generazione corretta
    ↓ se fallisce
SYSTEM_FUNCTION / compiler (hard, universali)
    ↓
correggono indipendentemente da M40
    ↓ se si ripete
nuova lesson in KB + fix proattivo
```

**Il sistema impara in due modi**:
1. **Da errori M40**: bug che si ripetono → fix nel compiler (deterministico)
2. **Da bug logici**: pattern che M40 tende a sbagliare → regola in SYSTEM_FUNCTION + lesson in KB (probabilistico — dipende da M40 che la legge e la applica)

**Limite attuale**: le lessons in KB influenzano M40 solo tramite il testo del prompt. M40 non è addestrabile — può ignorare una lesson se il contesto è troppo lungo o se il pattern non è abbastanza specifico. Per questo esiste il doppio meccanismo (KB + compiler).

---

## Stato attuale — Metriche

| Metrica | Valore |
|---------|--------|
| Lessons in KB (SQLite) | 32 |
| Snippets in KB | 60 |
| Fix proattivi in compiler.py | 9 funzioni |
| Regole in SYSTEM_FUNCTION | ~20 |
| Fix error-triggered in compiler.py | 9 pattern in `_API_ERROR_FIXES` |
| Task completati con successo | muretto, boids puri, predatore v1 |
| Task parziali (success visivo, done:false) | predatore v2/v3, Conway v1/v2/v3 |
| Patch medie per task (ultimi 5 task) | 1.4 |

**Trend**: il numero di patch per task si sta riducendo. La pipeline diventa più autonoma.
