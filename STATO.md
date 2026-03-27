# STATO — Programmatore di Arduini

> Ultima modifica: 2026-03-27 notte (run meteo DHT11+OLED v1 completata con 2 patch compile; fix evaluator.py None len bug; bug logico double-timer in readSensors da documentare e fixare in KB+SYSTEM_FUNCTION)

---

## STATO CORRENTE

### Infrastruttura
| Servizio | Stato | Note |
|----------|-------|------|
| MI50 (Qwen3.5-9B bfloat16) | ✅ porta 11434 | ROCm Docker, reasoning/planning/vision |
| M40 (Qwen3.5-9B Q5_K_M) | ✅ porta **11435** | llama-server, ctx=16384 |
| systemd llama-server-m40.service | ⛔ disabilitato | era Project Jedi Gemma-3-12B su porta 11435 |
| Dashboard SSE | ✅ porta 7700 | avvio standalone (nohup) |
| Raspberry Pi | ✅ 192.168.1.167 | rete eth0 Vodafone |
| ESP32 | ✅ /dev/ttyUSB0 | Snake S4 Due Serpenti caricato |
| Memory server | ✅ porta 7701 | Docker LLM-free |

> **⚠️ ATTENZIONE M40**: il systemd service `llama-server-m40.service` (Project Jedi, Gemma-3-12B,
> porta 11435) è stato fermato stanotte perché occupava la GPU. Qwen3.5-9B gira ora su porta **11436**
> e `m40_client.py` punta a 11436.
>
> **Per ripristinare Project Jedi**: `sudo systemctl start llama-server-m40.service`
> **Per riportare Qwen su 11435**: riavviare con `bash agent/start_servers.sh` e rimettere 11435 in `m40_client.py`
>
> **ATTENZIONE dopo ogni reboot**: `sudo ip link set eth0 up && sudo dhcpcd eth0`
> **Memory server dopo reboot**: `docker start memoria_ai_server`

### Avvio sessione
```bash
cd /home/lele/codex-openai/programmatore_di_arduini
source .venv/bin/activate
bash agent/start_servers.sh   # avvia MI50 + M40 + controlla VRAM
# Se M40 è ancora su porta 11436 (Qwen, manuale):
export LD_LIBRARY_PATH=/mnt/raid0/llama-cpp-m40/build_cuda/bin:/usr/local/cuda-11.8/lib64:/usr/lib/x86_64-linux-gnu
OMP_NUM_THREADS=8 /mnt/raid0/llama-cpp-m40/build_cuda/bin/llama-server \
  --model /mnt/raid0/models-gguf/Qwen3.5-9B-Q5_K_M.gguf \
  --host 0.0.0.0 --port 11436 --ctx-size 16384 --parallel 1 --threads 8 \
  --n-gpu-layers 99 --log-disable > /tmp/llama_qwen_11436.log 2>&1 &
```

---

## SESSIONE 2026-03-27 — Orologio v3b + Meteo DHT11

### Run orologio analogico v3b ✅
- **Zero patch** — M40 prima iterazione corretta grazie a lessons KB (cos/sin, setCursor, snprintf)
- Hardware: 3 lancette visibili, OCR `00:09:32`, tempo avanza tra frame
- Run dir: `logs/runs/20260327_081258_Sketch_ESP32_con_OLED_SSD1306_128x64_or/`

### Run stazione meteo DHT11+OLED v1 ⚠️ parziale
- **2 patch compile**: `DHTesp::readTemperature()` → `getTemperature()` + `getTextBounds(char*)` → `const char*`
- **Bug logico non catturato**: double-timer in `readSensors()` — `lastUpdate` aggiornato da `loop()` prima di chiamare `readSensors()`, quindi la condizione interna non scatta mai → T:0.0 H:0.0
- **Display hardware OK**: layout corretto (T/H text + barre orizzontali + UP counter)
- Run dir: `logs/runs/20260327_095900_Sketch_ESP32_con_OLED_SSD1306_128x64_st/`

### Fix infrastruttura applicati
- `observer.py`: max_tokens 600→1500 per ultimi 2 step + fallback da dati accumulati + OCR override
- `evaluator.py`: `len(None)` fix quando M40 ritorna `"dots": null` nel report compatto
- KB: 437 lessons (stabile — save_to_kb della run meteo non completata prima della pausa)

### Da fare alla prossima sessione
1. Fix `readSensors` double-timer → aggiungere lesson in KB + SYSTEM_FUNCTION anti-pattern
2. DHTesp API corrette in SYSTEM_FUNCTION: `TempAndHumidity data = dht.getTempAndHumidity()`
3. Rilanciare run meteo v2 con i fix per verificare lettura sensore reale

---

## SESSIONE 2026-03-22 NOTTE / 2026-03-23 MATTINA — Snake Definitivo

### Obiettivo
Costruire Snake su ESP32+OLED in 4 step progressivi con supervisione Claude (ruolo utente esperto).
Architettura progettata dal supervisore, codice generato da MI50+M40, risultati documentati in tempo reale.

### Risultati Snake Definitivo

| Step | Task | Risultato | Serial | Note |
|------|------|-----------|--------|------|
| S1 | Snake look-ahead | ✅ SUCCESS | EAT×2 SCORE:2,3 | 0 errori, 0 patch, 100% autonomia |
| S2 | Apprendimento evolutivo | ✅ SUCCESS (struttura) | GEN:4-8 SCORE:0 | Bug fisica M40 in updateSnake |
| S3 | Ostacoli + fisica corretta | ✅ SUCCESS | EAT×3 SCORE:1,2,3 | 0 errori, 0 patch, ostacoli funzionanti |
| S4 | Due serpenti in competizione | ✅ SUCCESS | EAT1×5 EAT2×9 in 45s | 3 patch manuali (dx/dy, opp, chooseDir) |

**Run dir S1**: `logs/runs/20260322_234853_Snake_Game_su_OLED_SSD1306_128x64_ESP32/`
**Run dir S2**: `logs/runs/20260323_003956_Snake_Game_su_OLED_SSD1306_128x64_ESP32/`
**Run dir S3**: `logs/runs/20260323_024955_Snake_con_Ostacoli_e_Apprendimento_su_OL/`

### Bug critico S2 — documentato e fixato in KB
M40 in `updateSnake()` spostava `pos[0]={nx,ny}` PRIMA dello shift del corpo →
`pos[1]=pos[0]=testa` → `isSafe(nx,ny)` trovava corpo[1]=testa → morte immediata ogni frame.
Ordine corretto: **(1) isSafe PRIMA, (2) shift i=length-1..1, (3) pos[0]={nx,ny}**.
Lesson aggiunta in KB come `snake_game / UPDATESNAKE ORDINE CRITICO`.

### Problema infrastruttura notte
Il systemd service `llama-server-m40.service` (Project Jedi) girava Gemma-3-12B su porta 11435
con ctx=4096. Generava 400 Bad Request su tutti i prompt di codice (troppo lunghi per ctx=4096).
Fix: M40 Qwen3.5-9B avviato manualmente su porta 11436, `m40_client.py` aggiornato.

### Documenti prodotti
- `docs/snake_definitivo_piano.md` — architettura S1→S4 completa
- `docs/snake_definitivo_sessione.md` — log in tempo reale della sessione
- `agent/snake_supervisor.py` — supervisore autonomo (orchestra i 4 step)
- `docs/00_abstract.md` — abstract del progetto (valutazione onesta del sistema)

---

## SESSIONE 2026-03-23 MATTINA — KB e Tooling

### Miglioramenti KB e search

**Problema identificato**: `search_kb` ignorava la query di MI50 (cercava sempre `sess.task`).
MI50 non sapeva di poter usare la KB come tool attivo durante planning e debug.

**Fix implementati in `agent/tool_agent.py`**:
1. `_search_kb`: ora usa `args["query"]` se fornito — MI50 può cercare quello che vuole
2. `_search_lessons`: nuovo tool — semantic search su anti-pattern e lessons (separato dai snippet di codice)
3. `_SYSTEM` prompt aggiornato: MI50 sa quando usare `search_lessons` (prima di plan_task, dopo errori compile, quando hardware non risponde)
4. Flusso aggiornato: step 0 = search_lessons (facoltativo ma consigliato)

**Lessons aggiunte**: 82 → **131 totali** (+49 in questa sessione)
| Categoria | Lessons aggiunte |
|-----------|-----------------|
| snake_game | 8 (updateSnake, lunghezza, circular buffer, chooseDir, evolutivo, starvation, ostacoli, init) |
| oled_ssd1306 | 6 (display(), fillRect, colori, costruttore, include, Wire.begin) |
| m40_behavior | 6 (updateSnake bug, length--, while(true), millis int, textWidth, score locale) |
| system_architecture | 4 (serial-first, KB nei prompt, resume, M40 ctx size) |
| esp32_hardware | 4 (WDT reset, random seed, serial baud, porta seriale) |
| interrupt | 8 (ISR breve, volatile, debounce ISR, atomic read, encoder, timer ESP32, timer AVR) |
| timer_nonbloccante | 4 (millis pattern, overflow, multi-timer, one-shot) |
| state_machine | 2 (enum pattern, transizioni) |
| eeprom | 2 (Preferences ESP32, EEPROM AVR) |
| pwm | 2 (LEDC ESP32, analogWrite AVR) |
| i2c | 2 (scan, multi-device) |
| debounce | 1 (software classico) |

**Tooling per espandere KB**:
- `docs/prompt_genera_lessons_kb.md` — prompt pronto da dare a LLM in chat per generare lessons JSON
- `knowledge/import_lessons.py` — script CLI: `python knowledge/import_lessons.py lessons.json`

**Prossimi argomenti da popolare**: WiFi ESP32, sensori I2C (MPU6050/BME280), display TFT, motori stepper, repo GitHub Paolo Aliverti

---

## SESSIONE 2026-03-22 — Occhio Bionico v2 + Observer Sub-Agent

### Observer sub-agent (M40) — completato ✅
```
MI50 chiama: observe_display({"goal": "verifica display"})
    ↓ (UNA SOLA tool call da MI50)
M40 mini-ReAct loop (context isolato, max 6 passi):
    check_display_on → capture_frames → detect_motion → count_objects → report
    ↓
{display_on, objects_total, dots, segments, motion_detected, success_hint, reason}
```
File: `agent/occhio/observer.py` — detect_motion override post-processing (medium/high → force True)

---

## ARCHITETTURA CORRENTE

### Modelli
| Modello | HW | Ruolo | Porta |
|---------|----|----|-------|
| Qwen3.5-9B bfloat16 | MI50 ROCm Docker | Reasoning, planning, vision | 11434 |
| Qwen3.5-9B Q5_K_M GGUF | M40 CUDA llama-server | Code generation | 11435 |

### Tool Agent — flusso ReAct (tool_agent.py)
```
[PREFLIGHT] 7 check automatici
     ↓
MI50: search_lessons (facoltativo, cerca anti-pattern prima di pianificare)
     ↓
MI50: plan_task → plan_functions
     ↓ (lessons KB per-funzione iniettate automaticamente)
M40:  generate_globals → generate_all_functions (ThreadPoolExecutor, parallelo)
     ↓
MI50: request_review ← NUOVO STEP 4.5 — attende review_response.txt (timeout 10 min)
     se has_issues → patch_code con BUG/FIX ricevuti
     ↓
compiler: fix_known_includes + fix_italian_pseudocode → compile
     se errori → search_lessons(errore) → patch_code (max 3 cicli)
     ↓
PlatformIO: upload_and_read → serial output ESP32
     ↓
evaluator: serial-first → observer(M40) → M40 judge → MI50 vision fallback
     ↓
learner: save_to_kb
     + salva review_notes come lessons task_type=review_fix
```

**request_review — come interagire:**
```bash
# Quando la run stampa "⏳ Attendo feedback in workspace/review_response.txt":
# Aprire workspace/review_request.md, leggere il codice, rispondere:
echo "ok" > workspace/review_response.txt
# oppure con bug:
echo "BUG: usa cos() per Y invece di sin() | FIX: cambiare con sin()" > workspace/review_response.txt
```

### Knowledge Base
| Storage | Contenuto | Count |
|---------|-----------|-------|
| SQLite `knowledge/arduino_agent.db` | snippets + lessons + libraries | **431 lessons** (+16 DHTesp +5 oled_trigonometry; +101 da generate_lessons.py) |
| ChromaDB `knowledge/chroma/` | vettori semantici per search | sincronizzato con SQLite |

```bash
# Conta lessons
sqlite3 knowledge/arduino_agent.db "SELECT COUNT(*) FROM lessons;"

# Cerca lessons per keyword
sqlite3 knowledge/arduino_agent.db \
  "SELECT task_type, lesson FROM lessons WHERE lesson LIKE '%updateSnake%';"

# Importa nuove lessons da JSON
python knowledge/import_lessons.py lessons_nuove.json
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

## TODO PROSSIMA SESSIONE

### 🔴 Priorità alta
1. ~~**Run orologio v3b**~~ ✅ COMPLETATA — zero patch, hardware OK, OCR `00:09:32`
2. ~~**Run meteo DHT11+OLED v1**~~ ✅ COMPLETATA (hardware) — 2 patch compile, bug logico double-timer (T:0.0), display layout OK
3. **Fix bug double-timer in readSensors** — M40 mette timer interno in readSensors MA loop() ha già aggiornato lastUpdate → sensore non legge mai. Fix: non usare timer dentro le funzioni di lettura, solo in loop()
4. **Aggiungere DHTesp API corrette a SYSTEM_FUNCTION** — `TempAndHumidity data = dht.getTempAndHumidity(); float t = data.temperature;` — M40 usa `readTemperature()` che non esiste
5. **Test request_review in modalità interattiva** — prossima run con `--interactive` flag per 600s review
6. **snake_definitivo_valutazione.md** — documento valutazione finale Snake (S1-S4)

### 🟡 Priorità media
5. **Espandere KB con Paolo Aliverti** — usare `docs/prompt_genera_lessons_kb.md` + `import_lessons.py`
6. **Argomenti KB mancanti** — WiFi ESP32, sensori I2C, display TFT, motori stepper
7. **M40 idle search** — mentre MI50 pensa, M40 fa ricerche KB in background e prepara contesto

### 🟢 Priorità bassa
8. **eth0 permanente sul Pi** — netplan config
9. **Resume fix completo** — synthetic turn injection in anchor_uploading (bug #30)

---

## FILE CHIAVE

```
agent/tool_agent.py      ← agente ReAct principale (search_lessons tool, SYSTEM prompt)
agent/compiler.py        ← fix_known_includes + fix_italian_pseudocode + regression detection
agent/generator.py       ← SYSTEM_GLOBALS/FUNCTION/PATCH
agent/evaluator.py       ← evaluate_visual (serial-first → observer → M40 → MI50)
agent/occhio/observer.py ← M40 sub-agent osservatore (detect_motion override)
agent/m40_client.py      ← porta 11435 ✅
agent/snake_supervisor.py ← supervisore autonomo sessione Snake
knowledge/db.py          ← snippet + lessons SQLite (add_lesson, search_lessons)
knowledge/semantic.py    ← ChromaDB semantic search
knowledge/import_lessons.py ← CLI import JSON lessons
docs/00_abstract.md      ← abstract progetto (pushato su GitHub)
docs/prompt_genera_lessons_kb.md ← prompt LLM per generare lessons
docs/snake_definitivo_piano.md   ← architettura S1→S4
docs/snake_definitivo_sessione.md ← log sessione Snake
logs/runs/               ← archivio run (checkpoint, codice, frame, serial, result)
```

---

## COMANDI RAPIDI

```bash
cd /home/lele/codex-openai/programmatore_di_arduini && source .venv/bin/activate

# Avvio servizi (ripristina porta 11435)
bash agent/start_servers.sh

# Run agente
python agent/tool_agent.py "task" --fqbn esp32:esp32:esp32

# Resume da checkpoint
python agent/tool_agent.py --resume logs/runs/<run_dir>

# Fix rete Pi (dopo reboot)
sudo ip link set eth0 up && sudo dhcpcd eth0

# Kill processi stuck sul Pi
ssh lele@192.168.1.167 "pkill -f esptool; pkill -f 'pio run'"

# KB
sqlite3 knowledge/arduino_agent.db "SELECT COUNT(*) FROM lessons;"
python knowledge/import_lessons.py lessons.json

# M40 Qwen su porta 11436 (se service Jedi occupa 11435)
export LD_LIBRARY_PATH=/mnt/raid0/llama-cpp-m40/build_cuda/bin:/usr/local/cuda-11.8/lib64:/usr/lib/x86_64-linux-gnu
OMP_NUM_THREADS=8 /mnt/raid0/llama-cpp-m40/build_cuda/bin/llama-server \
  --model /mnt/raid0/models-gguf/Qwen3.5-9B-Q5_K_M.gguf \
  --host 0.0.0.0 --port 11436 --ctx-size 16384 --parallel 1 --threads 8 \
  --n-gpu-layers 99 --log-disable > /tmp/llama_qwen_11436.log 2>&1 &
```
