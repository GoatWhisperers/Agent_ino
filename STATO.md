# STATO — Programmatore di Arduini

> Ultima modifica: 2026-03-21

---

## STATO CORRENTE

### Infrastruttura
| Servizio | Stato | Note |
|----------|-------|------|
| MI50 (Qwen3.5-9B bfloat16) | ✅ porta 11434 | reasoning/planning/vision |
| M40 (Qwen3.5-9B Q5_K_M) | ✅ porta 11435 | code generation parallelo |
| Dashboard SSE | ✅ porta 7700 | avvio standalone (nohup) |
| Raspberry Pi | ✅ 192.168.1.167 | rete eth0 Vodafone |
| ESP32 | ✅ /dev/ttyUSB0 LIBERA | muretto v2 caricato (fix fisica + collisioni) |
| Memory server | ✅ porta 7701 | Docker LLM-free, hash dedup + heat score (chroma_cache su volume persistente) |

> **ATTENZIONE dopo ogni reboot**: `sudo ip link set eth0 up && sudo dhcpcd eth0` per raggiungere il Pi
> **Memory server dopo reboot**: `docker start memoria_ai_server` — il modello all-MiniLM è in volume persistente, no download

### Avvio sessione
```bash
cd /home/lele/codex-openai/programmatore_di_arduini
source .venv/bin/activate
bash agent/start_servers.sh   # avvia MI50 + M40 + controlla VRAM
```

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

**Test end-to-end**: 3 test superati (visual-only, serial-first, percorsi errati)

**Lezione**: `docs/lezione_occhio_bionico.md`

**TODO aggiornato**: priorità ora è terzo run muretto (pipeline pronta e validata)

---

## SESSIONE 2026-03-21 — COMPLETATA ✅

### Task muretto v2 (fisica corretta): SUCCESSO

**Obiettivo**: Ripetere il muretto con task description COMPLETA (specifiche fisiche, pattern,
bug noti dalle run precedenti) per testare l'autonomia del programmatore.

**Run dir**: `logs/runs/20260321_083827_Gioco_OLED_SSD1306_128x64_su_ESP32_3_pa`

**Risultato**: ✅ GIOCO FUNZIONANTE — 3 palline in movimento visibili, 6 mattoncini, HIT/BREAK
su serial. Codice fixato manualmente in `workspace/muretto_fix/muretto_fix.ino`.

**Strategia adottata**: task description completa upfront → MI50 ha pianificato correttamente
al primo colpo, M40 ha generato 222 righe compilabili al primo tentativo.

**Bug trovati nel codice generato** (non rilevati da compilazione):
- A: Doppia inversione vy (updatePhysics + resolveBallBrickCollision) → HIT mai registrato
- B: Condizione `vy < 0` invertita per collisione dall'alto → mattoncini non colpiti
- C: `regenActive` mai settato `true` → rigenerazione non partiva mai
- D: Serial REGEN spam (ogni frame) invece di una volta sola

**Bug del sistema**:
- evaluate_visual falso negativo → patch loop inutile (3 cicli)
- M40 patch backtick → semplifica codice in stub
- Tool_agent loop su upload fallito (4 tentativi identici)

**Lessons salvate in KB** (5):
- OLED brick collision — collisione overlap minimo
- OLED physics simulation — rimbalzo bordi con abs()
- OLED game logic — startRegen() + regenActive
- evaluate visual — serial first, visual second
- M40 code generation — patch backtick non deve rimuovere logica

**Strategia generale per futura prove** salvata in memory:
`feedback_strategia_task_autonomia.md`

**Lezione**: `docs/lezione_muretto2.md`

**Sfondo webcam**: verde/neutro migliora significativamente evaluate_visual.

---

### TODO per prossima sessione

#### 🔴 Priorità alta
1. **Terza run muretto** con task che include tutte le correzioni:
   - Collisione mattoncini: overlap minimo (no check vy)
   - Bordi: abs() per garantire direzione corretta
   - startRegen() con regenActive esplicito
   - Hint seriale: passa expected_events=["HIT","BREAK"] a evaluate_visual
   - → obiettivo: zero intervento manuale, 100% autonomia
   - Pipeline evaluator ora pronta ✅ (serial-first + opencv+M40 validato)

#### 🟡 Priorità media
2. **eth0 permanente sul Pi** — netplan config
3. **Blob detection 2D** in evaluator: connected components invece di scan 1D per righe

#### 🟢 Priorità bassa
4. **Skill library** — funzioni Arduino testate e riusabili
5. **Doc ingestion** — datasheet in ChromaDB

---

## SESSIONE 2026-03-20 — COMPLETATA ✅

### Task muretto: SUCCESSO

**Obiettivo**: 3 palline che distruggono un muretto di 6 mattoncini su OLED 128x64.
Ogni mattoncino resiste 10 colpi. Rigenerazione random quando tutto distrutto.
Serial output: HIT / BREAK / REGEN.

**Run dir**: `logs/runs/20260320_162121_Gioco_OLED_SSD1306_128x64_su_ESP32_tre`

**Risultato**: ✅ GIOCO FUNZIONANTE — frame webcam mostrano 3 palline + muretto visibili.
Compilazione al primo tentativo, zero errori, 205 righe.

**evaluate_visual ha dato falso negativo** (display "nero" per sfondo rosso sfondo ambientale) —
ma i frame confermano visivamente il successo. Non fidarsi di `success=false` per task display
senza guardare i frame manualmente.

### Sistema "lessons" — PRIMO TEST SUPERATO ✅

Le 7 lezioni estratte da T4 (tre palline) sono state iniettate automaticamente in `plan_task`:
- MI50 ha scritto "impulso negativo", "overlap resolution", "drawBalls()" senza iniezione manuale
- Zero intervento supervisore sulla task description

**Confronto con T4**: T4 aveva bisogno di 2149 caratteri di specifiche manuali.
Il muretto ha compilato corretto al primo tentativo con 0 caratteri manuali aggiuntivi.

### Bug trovati e fixati

| # | Bug | File | Fix |
|---|-----|------|-----|
| 25 | MI50 loop su `plan_functions` in fase generating | `tool_agent.py` | Guard: se `sess.phase != PHASE_PLANNING` → error + reminder "chiama generate_globals" |
| 26 | Anchor GENERATING non mostrava funzioni pianificate | `tool_agent.py` | `_anchor_generating` ora mostra lista funzioni + warning "già eseguita" |
| 27 | Notebook (`nb`) non serializzato nel checkpoint | `tool_agent.py` | `to_dict()` salva `globals_hint`, `globals_code`, `funzioni` con stato/codice |
| 28 | `from_dict()` non inizializzava stato/codice funzioni | `tool_agent.py` | Usa `set_funzioni()` + loop restore per i codici già generati |
| 29 | `KeyError: 'codice'` al resume (funzioni senza chiave) | `notebook.py` | `context_for_function` accedeva `dep["codice"]` su dict senza la chiave — fix via set_funzioni |

### Comportamento MI50 questa sessione

**Positivo:**
- Ha recepito le lessons dalla KB senza supervisore
- Ha delegato tutto il codice a M40 (non ha scritto C++ da solo)
- Ha eseguito il ciclo grab_frames → evaluate_visual autonomamente per task OLED
- Ha fatto patch_code corretto identificando i backtick come errore

**Problema:**
- Ha chiamato `plan_functions` 3 volte in fase generating (ora fixato con guard)
- evaluate_visual falso negativo non l'ha saputo correggere (ha patchato inutilmente)

---

## SESSIONE 2026-03-20 — COMPLETATA ✅

### Completato oggi (sera/notte)
- ✅ **evaluate_visual fix DEFINITIVO** — `_preprocess_frames()` in `evaluator.py`: crop 60% centrale + upscale 2x + contrast 1.5x. Confermato `success=True` sui frame muretto
- ✅ **save_to_kb muretto** — 4 lessons salvate: ESP32 I2C Setup, SSD1306 Initialization, Visual Verification, Code Generation (no backtick)
- ✅ **Memory server chroma_cache persistente** — volume Docker `/mnt/raid0/memoria_ai/chroma_cache`, no download al restart (<500ms)
- ✅ **Memory server integrato in save_to_kb** — `tool_agent.py` chiama `/remember` al termine di ogni run
- ✅ **PREFLIGHT aggiornato** — STEP 5 memory server, numbering corretto

### TODO — Prossima sessione

#### 🔴 Priorità alta
1. **Nuova run muretto con fisica corretta** — il codice sull'ESP32 ha palline ferme (bug `vx*dt`). Rigenerare con:
   ```bash
   source .venv/bin/activate
   python agent/tool_agent.py "Gioco OLED SSD1306 128x64 su ESP32: 3 palline rimbalzanti che distruggono un muretto di 6 mattoncini (2x3). Ogni mattoncino resiste 10 colpi poi sparisce. Quando tutti distrutti si rigenerano in ordine random. Serial: HIT/BREAK/REGEN." --fqbn esp32:esp32:esp32
   ```
   Con le lessons in KB + fix fisica in `generator.py` dovrebbe girare in autonomia completa.

2. **eth0 permanente sul Pi** — dopo ogni reboot si perde la rete:
   ```bash
   ssh lele@192.168.1.167
   sudo nano /etc/netplan/50-cloud-init.yaml  # aggiungere: eth0: dhcp4: yes
   sudo netplan apply
   ```

#### 🟡 Priorità media
3. **Fix fisica tre palline T4** — codice in `workspace/tre_palline_fix/tre_palline_fix.ino`, valutare se uploadarlo o far rigenerare il sistema
4. **Lessons muretto in memoria condivisa** — registrare le 4 lessons estratte anche nel memory server `/remember` per Codex

#### 🟢 Priorità bassa
5. **Skill library** — `knowledge/skills.py` con funzioni Arduino testate e riusabili
6. **Doc ingestion** — indicizzare datasheet Adafruit SSD1306 + ESP32 in ChromaDB
7. **MemGPT summarization** — auto-compress turni vecchi tool_agent vicino al limite contesto

---

## ARCHITETTURA CORRENTE

### Modelli
| Modello | HW | Ruolo | Porta | Params |
|---------|----|----|-------|--------|
| Qwen3.5-9B bfloat16 | MI50 ROCm Docker | Reasoning, planning, vision, valutazione | 11434 | max_new_tokens=8192, thinking ON |
| Qwen3.5-9B Q5_K_M | M40 CUDA llama.cpp | Code generation veloce | 11435 | ctx=16384 |

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
arduino-cli: compile    → se errori: M40 patch_code → compile (max 3 cicli)
     ↓
PlatformIO su Pi: upload_and_read  → serial output ESP32
     ↓
webcam CSI: grab_frames  → 3 frame jpg
     ↓
MI50 vision: evaluate_visual  → success + reason (⚠ falso negativo noto con sfondo colorato)
     ↓
learner: save_to_kb  → snippet + lessons in ChromaDB + SQLite
     ↓
{done: true}
```

### Context Manager (MemGPT-style)
```
[system]  ~150 token — regole + flusso
[anchor]  phase-aware, ricostruito ogni step:
  planning   → task + FQBN + completati (summary)
  generating → task + approach + FUNZIONI PIANIFICATE (lista) + warning no-repeat
  compiling  → errori + righe codice vicine (±3 righe)
  uploading  → task + "codice OK"
  evaluating → task + serial_output + frame paths
[turns]   sliding window 5 turni (assistant + user result)
```

### Checkpoint / Resume
```bash
# Checkpoint salvato dopo ogni tool call in:
logs/runs/<YYYYMMDD_HHMMSS>_<slug>/checkpoint.json

# Il checkpoint include (da questa sessione):
# sess.nb.globals_hint, sess.nb.globals_code, sess.nb.funzioni (con stato+codice)

# Resume:
python agent/tool_agent.py --resume logs/runs/<run_dir>
```

### Sistema Lessons (knowledge/)
```
run completata
    → learner.extract_patterns() → MI50 estrae lessons strutturate
    → knowledge/db.py: add_lesson() → SQLite tabella lessons
    → knowledge/semantic.py: index_lesson() → ChromaDB collection "lessons"

plan_task / plan_functions:
    → _auto_enrich_task() → cerca lessons semanticamente in ChromaDB
    → inietta "=== LESSONS DA RUN PRECEDENTI ===" nel contesto MI50
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

### Snippet salvati
```bash
sqlite3 knowledge/arduino_agent.db \
  "SELECT task_description, board, created_at FROM snippets ORDER BY created_at DESC LIMIT 10;"
```
Presenti: pallina rimbalzante OLED, template base OLED, tre palline T4, (muretto da salvare)

### Lessons salvate (7 da T4)
```bash
sqlite3 knowledge/arduino_agent.db \
  "SELECT task_type, lesson FROM lessons ORDER BY created_at DESC LIMIT 10;"
```

---

## BUG NOTI NON ANCORA FIXATI

| Bug | Impatto | Fix pianificato |
|-----|---------|-----------------|
| evaluate_visual falso negativo con sfondo colorato | ~~Il sistema patcha inutilmente per 2+ cicli~~ | ✅ FIXATO: crop 60% centrale + upscale 2x + contrast 1.5x in `_preprocess_frames()` — confermato success=True |
| eth0 non persiste dopo reboot Pi | Richiede fix manuale ogni volta | Netplan config sul Pi |
| torchvision sparisce dopo restart Docker MI50 | evaluate_visual fallisce | Già nel Dockerfile ma richiede rebuild --no-cache |
| Memory server: all-MiniLM scaricato ad ogni restart | Primo /remember tarda 5+ min | ✅ FIXATO: volume /mnt/raid0/memoria_ai/chroma_cache montato in Docker |
| Fisica tre palline: palline quasi immobili (vx*dt bug) | Palline si muovono a 0.08px/frame | ✅ FIXATO: regola in generator.py SYSTEM_FUNCTION + lesson in KB |

---

## COMANDI RAPIDI

```bash
cd /home/lele/codex-openai/programmatore_di_arduini && source .venv/bin/activate

# Avvio servizi
bash agent/start_servers.sh

# Rebuild MI50 (se Dockerfile cambia)
docker stop mi50-server && docker rm mi50-server
docker build --no-cache -f docker/Dockerfile.mi50 -t mi50-server . && bash docker/run_mi50.sh

# Dashboard standalone
nohup python3 -c "
import sys; sys.path.insert(0, '.')
import agent.dashboard as d, time; d.start()
while True: time.sleep(60)
" > /tmp/dashboard.log 2>&1 &

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
agent/tool_agent.py      ← agente ReAct principale (guard plan_functions, nb serializzato)
agent/mi50_client.py     ← streaming token + HTTP batching verso dashboard
agent/mi50_server.py     ← server Flask Qwen3.5-9B ROCm (enable_thinking, vision)
agent/generator.py       ← SYSTEM_GLOBALS/FUNCTION/PATCH con regole SSD1306
agent/compiler.py        ← fix_known_includes, fix_known_api_errors
agent/orchestrator.py    ← plan_task, plan_functions, analyze_errors
agent/evaluator.py       ← evaluate_text, evaluate_visual (⚠ falso negativo OLED)
agent/learner.py         ← extract_patterns → salva snippet + lessons in KB
agent/notebook.py        ← Notebook: globals + funzioni (stato/codice per ogni funzione)
agent/grab.py            ← grab_now via SSH sul Pi
agent/remote_uploader.py ← upload PlatformIO + lettura seriale
agent/dashboard.py       ← Flask SSE porta 7700, frame persistenti su disco
knowledge/db.py          ← snippet + lessons SQLite
knowledge/semantic.py    ← ChromaDB: snippets + lessons collection
logs/runs/               ← archivio run con checkpoint, codice, frame, result
docs/                    ← lezioni e documentazione architetturale
```
- usa la memoria condivisa in /mnt/raid0/memoria_ai
