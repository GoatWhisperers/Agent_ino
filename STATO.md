# STATO — Programmatore di Arduini

> Ultima modifica: 2026-03-22 (sera — Progetto Snake L1✅ L2✅ L3✅ L4🔄, 85+ lessons KB)

---

## STATO CORRENTE

### Infrastruttura
| Servizio | Stato | Note |
|----------|-------|------|
| MI50 (Qwen3.5-9B bfloat16) | ✅ porta 11434 | reasoning/planning/vision |
| M40 (Gemma 3 12B Q4_K_M) | ✅ porta 11435 | **modello cambiato questa sessione** — code generation |
| Dashboard SSE | ✅ porta 7700 | avvio standalone (nohup) |
| Raspberry Pi | ✅ 192.168.1.167 | rete eth0 Vodafone |
| ESP32 | ✅ /dev/ttyUSB0 | Snake L3 caricato (L4 in corso) |
| Memory server | ✅ porta 7701 | Docker LLM-free, hash dedup + heat score |

> **ATTENZIONE dopo ogni reboot**: `sudo ip link set eth0 up && sudo dhcpcd eth0`
> **Memory server dopo reboot**: `docker start memoria_ai_server`

> **⚠ M40 ora usa Gemma 3 12B** (non Qwen3.5-9B) — più lento, ~15-20 tok/sec. Verificare al preflight.

### Avvio sessione
```bash
cd /home/lele/codex-openai/programmatore_di_arduini
source .venv/bin/activate
bash agent/start_servers.sh   # avvia MI50 + M40 + controlla VRAM
```

---

## SESSIONE 2026-03-22 (sera) — Progetto Snake

### Progetto Snake — avanzamento livelli

| Livello | Task | Stato | Patch | Bug M40 |
|---------|------|-------|-------|---------|
| L1 — Pixel rimbalzante | pixel 2x2 su OLED, BOUNCE su serial | ✅ 0 patch | 0 | nessuno |
| L2 — Corpo che segue | corpo 5 segmenti, circular buffer | ✅ 0 patch | 0 | nessuno (fix proattivi compiler) |
| L3 — Cibo + crescita | food random, EAT su serial, score | ✅ 1 patch | 1 manuale | 2 critici (loop infinito, prevX/prevY) |
| L4 — Game Over | self-collision + wall death + reset | 🔄 in corso | - | - |
| L5 — Navigazione autonoma | look-ahead, evita 180°, svolta libera | ⏳ - | - | - |
| L6 — Score + velocità | score display, delay 200→50ms | ⏳ - | - | - |
| L7 — Neuroevoluzione | rete neurale 3 input, pesi evoluti su ESP32 | ⏳ - | - | - |

**Lessons aggiunte in questa sessione**: ~5 lessons snake specifiche (randomFreePos, wall bounce, positions[0] head tracking)

**Fix sistemici scoperti in Snake**:
| Fix | File | Commit |
|-----|------|--------|
| Serial-first threshold 1 (era max(1,N//2)) | evaluator.py | 3d1fdda |
| Serial.begin() proattivo se mancante | compiler.py | a0bf835 |
| fillRect senza colore → SSD1306_WHITE auto | compiler.py | f015d7c |
| sess.eval_result {} nel serial-first path | tool_agent.py | f015d7c |
| expected_events estratti dal task string | tool_agent.py | 3fbd766 |
| anchor_done reason non più placeholder letterale | tool_agent.py | questa sessione |

**Bug M40 sistematici di Snake** (aggiunti ai task successivi come guardie esplicite):
- `randomFreePos()` → SEMPRE `for(int i<100)` non `while(true)` — ESP32 si blocca al boot
- `updatePhysics()` → SEMPRE `positions[0][0]` come testa, mai variabili float separate
- `checkWallCollision()` → non chiamare due volte per frame

---

## SESSIONE 2026-03-22 (notte) — Predatore v3 + Conway

### Task Predatore v3 (CATCH + RESPAWN con fix sistemici): PARZIALE ⚠️

**Run dir**: `logs/runs/20260322_002640_Simulazione_Boids_con_Predatore_su_displ`

**Risultato**: simulazione compilata e caricata. HUNT/CATCH visibili nel seriale, ma 4 bug nel codice generato da M40.

**Cosa funziona**: upload OK, HUNT/CATCH/RESPAWN eventi presenti, OLED mostra cerchi.

**Bug M40 nel codice generato** (tutti aggiunti a KB + SYSTEM_FUNCTION):
| Bug | Fix |
|-----|-----|
| `predator.id = nextPreyId++` → OOB (id=8, prey[8]) | `predator.id = 0` o `findNearestPrey()` |
| `lastRespawnTime` globale condiviso | campo `respawnTime` per-preda in struct Boid |
| `spawnPrey()` usa `nextPreyId` ciclico → RESPAWN:0 spam | `respawnPrey(int i)` con indice esplicito |
| Serial.print senza println → CATCH concatenato a HUNT | `Serial.println(fleeCount)` per terminare riga HUNT |

**Bug sistemici nel tool_agent scoperti**:
| # | Bug | Fix |
|---|-----|-----|
| 1 | Processo parte prima del commit → compiler.py OLD in memoria | Riavviare processo dopo ogni commit che tocca compiler.py |
| 2 | Fase `done` senza anchor → MI50 chiama patch_code in loop | `_anchor_done()` aggiunto in tool_agent.py |

**Autonomia**: ~40% (fix manuali per dist()+drawCircle, checkpoint update, resume × 3)

**Lezione**: `docs/lezione_predatore_v3.md` ✅

### Task Conway Game of Life v1: FALLITO ❌ (bug M40 + bug valutazione MI50)

**Run dir**: `logs/runs/20260322_014931_Conway_Game_of_Life_su_display_OLED_SSD1`

**Risultato**: compile OK, upload OK, evaluate_visual: M40 success=True. Ma MI50 in done phase: {success:false} perché vede GEN:229 ALIVE:204 × 40019 nel serial.

**Bug M40 nel codice generato** (tutti aggiunti a KB + SYSTEM_FUNCTION):
| Bug | Fix |
|-----|-----|
| Double `swapGrids()` (in computeNextGeneration + in loop) | swap SOLO in loop(), computeNextGeneration NON chiama swap |
| Bit packing errato in `initRandomGrid()` (x%BITMAP_COLS, x/BITMAP_COLS) | colonna=x/8, bit=x%8 — usare helper getCell/setCell |
| `checkStability()` usa `7-(x%8)` invece di `x%8` | usare getCell() helper |
| `gridX = y*BITMAP_COLS+bitCol` sbagliato in computeNextGeneration | iterate su for(y) for(x) con getCell(x,y) |
| Serial spam: printStatus() senza millis() check causa 4000 righe/sec | timer millis() in loop(), non dentro printStatus() |

**Bug sistemici pipeline scoperti** (tutti fixati):
| Bug | Fix |
|-----|-----|
| MI50 in done phase vede serial raw (8 righe identiche) → falso negativo | `_anchor_done` usa `_serial_summary()` + mostra `eval_result` esplicito |
| KB lessons aggiunte a SQLite ma non a ChromaDB | `db.add_lesson()` ora chiama `index_lesson()` automaticamente |
| M40 patcher non vede KB lessons rilevanti | `_patch_code` inietta lessons da SQLite fallback |
| `_anchor_compiling` senza lessons KB | KB lessons iniettate nel compiling anchor |

**Lezione**: `docs/lezione_conway_v1.md` ✅

### Task Conway Game of Life v3: ✅ PARZIALE (serial-first success, done:false da bug pipeline)

**Run dir**: `logs/runs/20260322_034956_Conway_s_Game_of_Life_su_OLED_SSD1306_12`

**Risultato**: compile OK (#2, dopo 1 patch). Upload OK. Serial: `Generation:0 Alive:463 Stable:0`. evaluate_visual: success=True [serial-first]. RUN END: FAILED (done JSON senza `"success":true` — bug appena fixato, commit `7eab4a2`).

**Bug M40 fixati rispetto v2**: delay(16) funziona (solo 3 righe serial in 10s), firma uint8_t correta.

**Bug M40 nuovi in v3**:
| Bug | Fix sistemico |
|-----|--------------|
| `bool isStable` come variabile E funzione stesso nome | NAMING rule aggiunta a SYSTEM_FUNCTION |
| `display.setPixel()` (non esiste) invece di `drawPixel()` | `_fix_setPixel_to_drawPixel()` in compiler.py |

**Autonomia**: ~90% (solo 1 patch compile autonoma)

**Lezione**: `docs/lezione_conway_v3.md` ✅

### Fix sistemici fatti questa mattina (sessione autonoma):
| Fix | File | Commit |
|-----|------|--------|
| Loop detection (stesso tool ×3 → hint) | tool_agent.py | 9aa4aab |
| plan_task guard fasi avanzate | tool_agent.py | 9aa4aab |
| Checkpoint write atomico | tool_agent.py | 9aa4aab |
| learner iterations usa logger._compile_errors | tool_agent.py | 9aa4aab |
| Double index_lesson rimosso dal learner | learner.py | 9aa4aab |
| anchor_done con JSON esplicito success=true/false | tool_agent.py | 7eab4a2 |
| _fix_setPixel_to_drawPixel in compiler.py | compiler.py | 663622f |
| NAMING/DISPLAY rule in SYSTEM_FUNCTION | generator.py | 663622f |

### Fix pomeriggio (sessione con Lele):
| Fix | File | Commit |
|-----|------|--------|
| Ricerca KB per-funzione in generate_all_functions | tool_agent.py | 1dce020 |
| generate_function() accetta function_lessons | generator.py | 1dce020 |
| Guard generate_globals in fasi avanzate | tool_agent.py | 1dce020 |
| Guard generate_all_functions in fasi avanzate | tool_agent.py | 1dce020 |
| ingest_docs.py: +24 lessons da file lezione_*.md | knowledge/ | 1dce020 |
| KB passages da 32 a **56 lessons** | ChromaDB+SQLite | 1dce020 |
| _patch_code(): check void setup()/loop() post-patch | tool_agent.py | 5004cc6 |
| +26 lessons da 8 docs non estratti → **82 lessons** | knowledge/ | 5004cc6 |

### Task Conway Game of Life v2: ✅ PARZIALE (success visivo, done:false da pipeline)

**Run dir**: `logs/runs/20260322_024218_Conway_s_Game_of_Life_su_OLED_SSD1306_12`

**Risultato**: compile OK (#3, dopo 2 patch). Upload OK. evaluate_visual: success=True (MI50-vision conferma pixel bianchi). RUN END: FAILED (done phase senza eval_result in anchor — processo pre-commit).

**Serial**: "Generation: 202\nAlive cells: 49" + serial spam (80142 righe/10s — causa non determinata).

**Bug M40 fissi in v2 rispetto v1**: swap corretto, bit packing corretto, getCell/setCell corretti, compute iterate xy corretti.

**Bug M40 rimasti**:
| Bug | Fix pianificato |
|-----|-----------------|
| `uint8_t* grid` invece di `uint8_t grid[][16]` | Fix proattivo aggiunto a compiler.py |
| Backtick in patch | SYSTEM_PATCH già gestisce |
| Serial spam (timer millis non funziona correttamente) | `delay(16)` in loop() + gestione stable→reinit |

**Autonomia**: ~85% (solo 2 patch compile automatiche)

**Lezione**: `docs/lezione_conway_v2.md` ✅

---

## SESSIONE 2026-03-21 (sera) — Predatore v2

### Task Predatore v2 (CATCH + RESPAWN): PARZIALE ⚠️

**Run dir**: `logs/runs/20260321_192028_Simulazione_Boids_con_Predatore_su_displ`

**Risultato**: simulazione compilata e caricata sull'ESP32. Display attivo (9 cerchi). Serial output funzionante.

```
HUNT:4 DIST:73.66 FLEE:1   → predatore cambia target
HUNT:0 DIST:25.69 FLEE:1
HUNT:2 DIST:12.62 FLEE:1   ← predatore a 12px dalla preda
HUNT:7 DIST:6.43 FLEE:1    ← quasi catch!
```

**Cosa funziona**: boids physics, predatore che caccia, target switching, display OLED.

**Bug M40 nel codice generato**:
| Bug | Causa | Fix necessario |
|-----|-------|----------------|
| `preySpawnTimer` usa conteggio iterazioni | `preySpawnTimer--` in loop invece di millis() | Usare `unsigned long spawnTime = millis()` |
| `FLEE:` stampa `prey[i].alive` (0/1) | M40 ha confuso alive status con flee count | Contare le prede a distanza < FLEE_RADIUS |
| Fisica si congela dopo ~1 min | Causa sospetta: float NaN nella cattura | Debug necessario |
| `int lastSerialTime = 0` invece di `unsigned long` | tipo sbagliato | Dichiarare `unsigned long` |

**CATCH/RESPAWN**: Non confermati nel serial output (spawn timer usa iterazioni non ms → 32s invece di 2s).

**Autonomia**: ~30% (molti interventi manuali, MI50 bloccato in loop, timeout, ctx clearing necessario).

---

### Fix sistemici scoperti questa sessione (sera)

| # | Fix | File | Motivo |
|---|-----|------|--------|
| 1 | Timeout MI50 3600→7200s | `mi50_client.py` | MI50 a ~2 tok/sec impiega 68 min per 8192 tok |
| 2 | Retry automatico `generate_all_functions` | `tool_agent.py` | M40 timeout silenzioso → ok:False + retry |
| 3 | Checkpoint ctx clearing quando phase=uploading | tool_agent.py | MI50 con ctx vecchio ignora anchor, ripartenza da planning |

---

## SESSIONE 2026-03-21 (pomeriggio) — IN FINALIZZAZIONE

### Task Boids puri: SUCCESSO 100% ✅

**Run dir**: `logs/runs/20260321_140451_Simulazione_Boids_stormo_emergente_su`

**Risultato**: ✅ STORMO FUNZIONANTE — 0 errori compilazione, 0 patch, 0 intervento manuale.
Stormo di 8 boid con Separazione + Allineamento + Coesione. **100% autonomia**.

**Lezione**: `docs/lezione_boids_puri.md` (da scrivere — TODO)

---

### Task Predatore Boids: SUCCESSO ✅

**Run dir**: `logs/runs/20260321_162709_Simulazione_Boids_con_Predatore_su_displ`

**Risultato**: ✅ PREDATORE FUNZIONANTE — serial output confermato:
```
HUNT:5 DIST:13 FLEE:2    → seek funziona
HUNT:2 DIST:5  FLEE:8    → TUTTE le 8 prede in fuga!
```

**Autonomia**: ~60% (1 intervento manuale per checkpoint update)

**Bug sistemici trovati e FIXATI** (commit `d617ec9` + questa sessione):

| # | Bug | Fix |
|---|-----|-----|
| 1 | M40 genera pseudocodice italiano senza `//` | `fix_italian_pseudocode()` in `compiler.py` |
| 2 | M40 patcher riduce codice da 253 → 50 righe | Regression detector in `_patch_code()`: < 60% → discard |
| 3 | SYSTEM_PATCH non vincolava volume output | "ALMENO tante righe quante in input" aggiunto a `SYSTEM_PATCH` |

**Lezione**: `docs/lezione_predatore_completa.md` ✅

---

### Fix sistemici questa sessione (in ordine cronologico)

1. `fix_italian_pseudocode()` in `compiler.py` — auto-corregge pseudocodice senza `//`
2. Regression detector in `tool_agent.py` `_patch_code()` — protegge da M40 patcher regressivo
3. `SYSTEM_PATCH` rafforzato in `generator.py` — vincola M40 a non ridurre il codice
4. Documentazione: `docs/lezione_predatore_completa.md`, `docs/divulgazione/per_tommaso.md`
5. GitHub: repo GoatWhisperers/Agent_ino aggiornata (README, docs, code)

---

### TODO per prossima sessione

#### 🔴 Priorità alta
1. **Prossimo task**: Snake Game su OLED SSD1306 — testa la ricerca KB per-funzione end-to-end
2. **Resume fix completo**: quando si fa resume con ctx vuoto in fase UPLOADING, MI50 chiama plan_task → synthetic turn injection non ancora implementato (bug #30 parziale)
3. **Patcher M40 loop() deletion**: dopo patch multi-round verificare che setup() e loop() esistano ancora (lesson in KB ma check non in compiler.py)

#### 🟡 Priorità media
4. **Multi-predatore** — 2 predatori cooperanti (seek + avoid altri predatori)
5. **eth0 permanente sul Pi** — netplan config
6. **Conway: piano successl**: Conway v3 ha avuto serial-first success → fare Conway v4 con color palette o regole personalizzate

#### 🟢 Priorità bassa
7. **Blob detection 2D** in evaluator: connected components invece di scan 1D
8. **Skill library** — funzioni Arduino testate e riusabili
9. **Doc ingestion** — datasheet in ChromaDB

---

## SESSIONE 2026-03-21 (parte 2) — COMPLETATA ✅

### Occhio bionico: esperimenti e implementazione

**Obiettivo**: Testare e validare il nuovo pipeline visivo (opencv+M40) prima di un terzo run muretto.

**Risultati esperimenti**:
- Display OFF (black image): white_ratio=0%, blob=0 → M40 dice success=False ✅
- Sfondo casuale (rumore grigio): white_ratio~0% → success=False ✅
- Display OLED attivo: white_ratio~24%, blob_piccoli=10-12, animation=True → success=True ✅
- Frames vecchi (fisica rotta ma display ON): success=True → **limite confermato**
- Serial-first con HIT: success=True in 0.1s ✅

**Limite identificato**: la pixel analysis NON distingue fisica corretta da fisica rotta.
Il seriale (HIT/BREAK) è il vero verificatore funzionale.

**Fix implementati in `evaluator.py`**:
1. Serial-first fast-path (Step 0): se eventi seriali trovati → return immediato
2. Guard "errore analisi": se tutti i frame hanno errore PIL → skip M40, vai a MI50
3. Nota riflessi ambientali nel prompt M40: "white_ratio>15% = riflessi, ignora blob_grandi"
4. Rimozione serial_confirms (era duplicato del serial-first già in tool_agent.py)

**Lezione**: `docs/lezione_occhio_bionico.md`

---

## SESSIONE 2026-03-21 — COMPLETATA ✅

### Task muretto v2 (fisica corretta): SUCCESSO
**Run dir**: `logs/runs/20260321_083827_Gioco_OLED_SSD1306_128x64_su_ESP32_3_pa`
**Risultato**: ✅ GIOCO FUNZIONANTE — 3 palline, 6 mattoncini, HIT/BREAK su serial.
**Lezione**: `docs/lezione_muretto2.md`

---

## ARCHITETTURA CORRENTE

### Modelli
| Modello | HW | Ruolo | Porta | Params |
|---------|----|----|-------|--------|
| Qwen3.5-9B bfloat16 | MI50 ROCm Docker | Reasoning, planning, vision, valutazione | 11434 | max_new_tokens=8192, thinking ON |
| Gemma 3 12B Q4_K_M | M40 CUDA llama.cpp | Code generation veloce | 11435 | ctx=16384 |

### Tool Agent — flusso ReAct (tool_agent.py)

```
[PREFLIGHT] 7 check automatici (~30s)
     ↓
MI50: plan_task         → approccio + librerie + vcap_frames (0 per default)
     ↓ (lessons KB iniettate automaticamente)
MI50: plan_functions    → 8 funzioni: firma + compito + dipendenze
     ↓ (GUARD: non ripetibile in fase generating)
M40:  generate_globals  → #include, #define, variabili globali
     ↓
M40:  generate_all_functions  → ThreadPoolExecutor, tutte in parallelo
     ↓
compiler: fix_known_includes + fix_italian_pseudocode → auto-corregge prima di compile
arduino-cli: compile    → se errori: M40 patch_code → regression check → compile (max 3 cicli)
     ↓
PlatformIO su Pi: upload_and_read  → serial output ESP32
     ↓
webcam CSI: grab_frames  → 3 frame jpg
     ↓
evaluator: evaluate_visual (serial-first → PIL pixel → M40 judge → MI50 vision fallback)
     ↓
learner: save_to_kb  → snippet + lessons in ChromaDB + SQLite
     ↓
{done: true}
```

### Hardware
| Componente | Dettaglio |
|-----------|-----------|
| Raspberry Pi 3B | `lele@192.168.1.167`, pwd: `pippopippo33$$` |
| Accesso rete | eth0 (Vodafone 192.168.1.1) — NON eth3 (Fastweb) |
| ESP32 NodeMCU | `/dev/ttyUSB0` sul Pi, baud 115200, FQBN `esp32:esp32:esp32` |
| OLED SSD1306 | 128x64, SDA=GPIO21, SCL=GPIO22, addr=0x3C, rst_pin=-1 |
| Webcam CSI IMX219 | `/dev/video0` sul Pi |

---

## KNOWLEDGE BASE

### Librerie arduino-cli installate
- Adafruit GFX Library 1.12.5
- Adafruit SSD1306 2.5.16
- Adafruit BusIO 1.17.4

### Snippets e lessons
```bash
# Snippets:
sqlite3 knowledge/arduino_agent.db \
  "SELECT task_description, created_at FROM snippets ORDER BY created_at DESC LIMIT 5;"

# Lessons:
sqlite3 knowledge/arduino_agent.db \
  "SELECT task_type, lesson FROM lessons ORDER BY created_at DESC LIMIT 10;"
```

---

## BUG NOTI NON ANCORA FIXATI

| Bug | Impatto | Fix pianificato |
|-----|---------|-----------------|
| eth0 non persiste dopo reboot Pi | Richiede fix manuale ogni volta | Netplan config sul Pi |
| torchvision sparisce dopo restart Docker MI50 | evaluate_visual fallisce | Già nel Dockerfile ma richiede rebuild --no-cache |
| M40 cambiato a Gemma 3 12B (non Qwen) | Comportamento diverso, più lento | Verificare prompt compatibility al preflight |

---

## COMANDI RAPIDI

```bash
cd /home/lele/codex-openai/programmatore_di_arduini && source .venv/bin/activate

# Avvio servizi
bash agent/start_servers.sh

# Run agente
python agent/tool_agent.py "task" --fqbn esp32:esp32:esp32

# Resume da checkpoint
python agent/tool_agent.py --resume logs/runs/<run_dir>

# Fix rete Pi (dopo reboot)
sudo ip link set eth0 up && sudo dhcpcd eth0
sudo ip route add 192.168.1.167 dev eth0

# Kill processi stuck sul Pi
ssh lele@192.168.1.167 "pkill -f esptool; pkill -f 'pio run'"

# KB
sqlite3 knowledge/arduino_agent.db \
  "SELECT task_description, created_at FROM snippets ORDER BY created_at DESC LIMIT 5;"

# Memory server (Claude+Codex)
curl -s http://127.0.0.1:7701/health
curl -s 'http://127.0.0.1:7701/recall?project=programmatore_di_arduini&query=OLED&n=3'
```

---

## FILE CHIAVE

```
agent/tool_agent.py      ← agente ReAct principale
agent/compiler.py        ← fix_known_includes + fix_italian_pseudocode + regression detection
agent/generator.py       ← SYSTEM_GLOBALS/FUNCTION/PATCH con regole SSD1306
agent/orchestrator.py    ← plan_task, plan_functions, analyze_errors
agent/evaluator.py       ← evaluate_text, evaluate_visual (serial-first pipeline)
agent/learner.py         ← extract_patterns → salva snippet + lessons in KB
agent/notebook.py        ← Notebook: globals + funzioni (stato/codice per ogni funzione)
agent/grab_tool.py       ← grab_now via SSH sul Pi
agent/remote_uploader.py ← upload PlatformIO + lettura seriale
agent/dashboard.py       ← Flask SSE porta 7700, frame persistenti su disco
knowledge/db.py          ← snippet + lessons SQLite
knowledge/semantic.py    ← ChromaDB: snippets + lessons collection
logs/runs/               ← archivio run con checkpoint, codice, frame, result
docs/                    ← lezioni e documentazione architetturale
docs/divulgazione/       ← per_tommaso.md e materiali divulgativi
```
