# STATO — Programmatore di Arduini

> Leggere SUBITO all'inizio di ogni sessione.
> Ultima modifica: 2026-03-11 sera

---

## DOVE SIAMO RIMASTI

**Task OLED emoticon COMPLETATO** — ESP32 mostra :) :( :D in sequenza automatica ogni 2s,
comandi seriali `happy` / `sad` / `big` funzionanti, verificato via webcam CSI.

Pipeline end-to-end completata manualmente. Tutte le fix applicate e documentate.
Dashboard attiva su `http://localhost:7700` con le 4 foto del display OLED caricate persistentemente.

**Prossimo step**: run completa end-to-end con nuovo task per testare tutte le fix insieme.

---

## COSA FUNZIONA

| Componente | Stato | Note |
|---|---|---|
| Fase 0 — Analyst | ✅ | funziona |
| Fase 1 — Orchestrator (plan_task) | ✅ | `note_tecniche` + `vcap_frames` nel piano |
| Fase 1b — Orchestrator (plan_functions) | ✅ | piano funzioni con `required_keys` fix |
| Fase 2 — Generator globals (M40) | ✅ | SYSTEM_GLOBALS con REGOLA INCLUDE |
| Fase 2 — Generator funzione (M40) | ✅ | globals → helpers → setup → loop |
| Fase 2 — Generator monolitico (fallback) | ✅ | ctx 16384 |
| Fase 2b — Patcher (M40) | ✅ | SYSTEM_PATCH dedicato, non aggiunge include inutili |
| Fase 3 — Compiler arduino-cli | ✅ | esp32:esp32@3.3.7, fatal error parsato |
| Fase 3 — fix_known_includes() | ✅ | SSD1306.h → Adafruit_SSD1306.h auto-fix |
| Fase 3 — check_libraries() | ✅ | verifica libs prima della run, si ferma se mancano |
| Fase 4 — PlatformIO + Upload Raspberry | ✅ | upload prima del grab (fix porta occupata) |
| Fase 4 — Lettura seriale post-boot | ✅ | reset_input_buffer() + attesa 3s |
| Fase 5 — Evaluator seriale | ⚠️ | loop() silenzioso → skip evaluation (TODO: aggiungi READY) |
| Fase 5 — Evaluator VCAP | ✅ | grab_now() dopo upload, frame → dashboard → MI50 |
| Fase 6 — Learner | ❌ | non testato |
| Notebook operativo | ✅ | `agent/notebook.py` |
| Dashboard real-time | ✅ | porta 7700, frame persistenti su disco, streaming token |
| MI50 Docker | ✅ | enable_thinking=False funziona, mount corretto |

---

## ARCHITETTURA CORRENTE

### Modelli e GPU
- **MI50** (AMD gfx906/Vega20, 32 GB VRAM, ROCm 6.2): Qwen3.5-9B bfloat16, PyTorch eager, porta 11434
  - `attn_implementation="eager"` — no Triton, no flash-attn (gfx906 non supporta)
  - `enable_thinking=False` in `apply_chat_template` → risposta ~5 min
  - `MAX_INPUT_TOKENS = 6144` (OOM prevention)
  - Gira dentro Docker con GPU passthrough zero-overhead
- **M40** (NVIDIA sm_52, 11.5 GB VRAM, CUDA): Qwen3.5-9B Q5_K_M GGUF, llama-server, porta 11435
  - `--ctx-size 16384` (6.5 GB modello + ~2.3 GB KV cache)

### Flusso codice (aggiornato)
1. **Fase 0** — Analyst MI50: recupera snippet KB, analizza cosa riusare
2. **Fase 1** — Orchestrator MI50: `plan_task()` → approccio, librerie, vcap_frames
3. **Fase 1b** — Orchestrator MI50: `plan_functions()` → lista funzioni con firme
4. **Fase 2** — Generator M40: `generate_globals()` + `generate_function(f)` per ogni f
5. **Fase 3** — Compiler: arduino-cli → errori → MI50 analizza → M40 patcha (max 5x)
6. **Fase 4** — Upload: PlatformIO su Raspberry → boot ESP32 → lettura seriale
7. **Fase 4b** — VCAP: `grab_now()` cattura N frame webcam → SCP → dashboard
8. **Fase 5** — Evaluator MI50: serial output + frame → valutazione → suggerimenti
9. **Fase 6** — Learner: salva snippet nel KB (non testato)

### Dashboard
- Avvio automatico a ogni `python agent/loop.py`
- Avvio manuale: `python -c "import agent.dashboard as d; d.start(); import time; time.sleep(9999)"`
- Accessibile su `http://localhost:7700`
- Contenuto: streaming token MI50/M40, badge funzioni ⚙→✓, frame webcam (clic per ingrandire), log seriale

### Hardware
| Dispositivo | Dettagli | Stato |
|---|---|---|
| Raspberry Pi 3B | YOUR_RPI_IP, pwd: YOUR_PASSWORD | ✅ |
| ESP32 NodeMCU | /dev/ttyUSB0 su Raspberry, baud 115200 | ✅ |
| OLED SSD1306 128x64 | SDA=GPIO21, SCL=GPIO22, I2C addr=0x3C | ✅ |
| Webcam CSI (IMX219) | /dev/video0 su Raspberry | ✅ |

**Librerie PlatformIO su Raspberry** (pre-installate in `~/.platformio/lib/`):
- Adafruit_SSD1306, Adafruit-GFX-Library, Adafruit_BusIO
- platformio.ini DEVE avere: `lib_extra_dirs = ~/.platformio/lib`

---

## BUG NOTI / TODO

### [PRIORITÀ 1] Evaluator skip su loop() silenzioso
- **Problema**: sketch che non stampano nulla in loop() vengono valutati come "empty serial" → skip
- **Fix**: assicurarsi che SYSTEM_PROMPT/PATCH preservino `Serial.println("READY")` in setup()
- **File**: `agent/generator.py` SYSTEM_PROMPT — la regola c'è, verificare che il patcher non la rimuova

### [PRIORITÀ 2] Testare run completa end-to-end
- Le fix 10/11/12 (VCAP port conflict, pkill stuck, frame persistenti) non sono ancora state
  testate in una run automatica completa — solo in test manuali
- Fare una run con nuovo task OLED o LED per verificare tutto il pipeline

### [PRIORITÀ 3] Testare Learner (Fase 6)
- Non testato in nessuna run completa

### [FIX APPLICATI QUESTA SESSIONE — già nel codice]
- ✅ pkill esptool/pio prima di ogni upload (`loop.py`)
- ✅ VCAP: upload prima, poi grab_now (`loop.py`)
- ✅ Regola rst_pin=-1 SSD1306 in SYSTEM_GLOBALS e FuncPlanner (`generator.py`, `orchestrator.py`)
- ✅ Dashboard frame persistenti su disco (`dashboard.py`, `workspace/.frames_cache.json`)

---

## COMANDI RAPIDI

```bash
# Avvio tutto (SEMPRE usare questo)
cd /home/lele/codex-openai/programmatore_di_arduini && source .venv/bin/activate
bash agent/start_servers.sh

# Stato server
curl -s localhost:11434/health && curl -s localhost:11435/health

# Dashboard standalone persistente (sopravvive alla chiusura di loop.py)
nohup python3 -c "
import sys; sys.path.insert(0, '.')
import agent.dashboard as d, time
d.start()
while True: time.sleep(60)
" > /tmp/dashboard.log 2>&1 &

# Run agente (+ dashboard su http://localhost:7700)
python agent/loop.py "task" --fqbn esp32:esp32:esp32

# Solo compilazione (no hardware)
python agent/loop.py "task" --fqbn esp32:esp32:esp32 --no-upload

# Kill processi stuck sul Raspberry
ssh lele@YOUR_RPI_IP "pkill -f esptool; pkill -f 'pio run'"

# Seriale Raspberry (debug)
ssh lele@YOUR_RPI_IP "python3 -c \"
import serial,time
s=serial.Serial('/dev/ttyUSB0',115200,timeout=0.3)
s.reset_input_buffer()
time.sleep(2)
buf=b''.join([s.read(128) for _ in range(30)])
s.close()
print(''.join(chr(b) if 32<=b<127 or b in(10,13) else '.' for b in buf)[:500])
\""

# Ultimo log
tail -f logs/$(ls -t logs/ | head -1)

# Notebook dell'ultimo task
cat workspace/current/*/notebook.json | python3 -m json.tool | head -60

# Knowledge base
sqlite3 knowledge/arduino_agent.db "SELECT task_description, board, created_at FROM snippets ORDER BY created_at DESC LIMIT 5;"

# Build Docker MI50 (se necessario)
docker build -f docker/Dockerfile.mi50 -t mi50-server . 2>&1 | tee /tmp/mi50_docker_build.log
docker stop mi50-server && docker rm mi50-server && bash docker/run_mi50.sh
```

---

## DOCKER MI50 — dettagli tecnici

**Immagine:** `mi50-server:latest`

**ENV critici:**
- `HSA_OVERRIDE_GFX_VERSION=9.0.6` — architettura reale MI50 (Vega20/gfx906)
- `HIP_VISIBLE_DEVICES=0`
- `HSA_ENABLE_SDMA=0`
- `PYTORCH_HIP_ALLOC_CONF=max_split_size_mb:128,...,expandable_segments:True`
- `HF_HOME=/mnt/raid0/hf_cache`

**Mount critico:** `-v agent/mi50_server.py:/app/mi50_server.py:ro`
(il server gira da `/app/mi50_server.py`, NON da `/app/agent/mi50_server.py`)

**Docker data-root:** `/mnt/raid0/docker-data`
**Modello:** `/mnt/raid0/qwen3.5-9b/` (montato read-only)

---

## CALCOLO CONTESTI

### MI50 — Qwen3.5-9B (HuggingFace, bfloat16, eager attention)
- VRAM totale: 32 GB | Modello: ~18 GB | Libera: ~14 GB
- **MAX_INPUT_TOKENS = 6144** (hardcoded in `mi50_server.py`)

### M40 — Qwen3.5-9B Q5_K_M (llama.cpp GGUF)
- VRAM totale: 11.5 GB | Modello: ~6.5 GB
- **--ctx-size = 16384** (in `start_servers.sh`)
