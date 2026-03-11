# STATO — Programmatore di Arduini

> Leggere SUBITO all'inizio di ogni sessione.
> Ultima modifica: 2026-03-11 pomeriggio

---

## DOVE SIAMO RIMASTI

**Tool Agent implementato** — l'agente usa ora un loop ReAct in cui MI50 decide
autonomamente quali tools chiamare e quando. La webcam viene usata senza hardcoding
nel loop: il modello la chiama da solo quando il task lo richiede.

**Dashboard aggiornata** — taskbar Start/Stop, bottone grab webcam, pulizia automatica
al Play, stato Start/Stop corretto in base allo stato del processo.

**In corso**: primo test completo del tool_agent con task astronave OLED.

---

## ARCHITETTURA CORRENTE

### Modelli e GPU
- **MI50** (AMD gfx906/Vega20, 32 GB VRAM, ROCm 6.2): Qwen3.5-9B bfloat16, porta 11434
  - Reasoning, planning, analisi errori, valutazione — con thinking abilitato
  - `MAX_INPUT_TOKENS = 6144`, `enable_thinking=True` ovunque
  - Gira dentro Docker con GPU passthrough
- **M40** (NVIDIA sm_52, 11.5 GB VRAM, CUDA): Qwen3.5-9B Q5_K_M GGUF, porta 11435
  - Code generation veloce — `--ctx-size 16384`

### Hardware
| Dispositivo | Dettagli | Stato |
|---|---|---|
| Raspberry Pi 3B | 192.168.1.167, pwd: pippopippo33$$ | ✅ |
| ESP32 NodeMCU | /dev/ttyUSB0 su Raspberry, baud 115200 | ✅ |
| OLED SSD1306 128x64 | SDA=GPIO21, SCL=GPIO22, I2C addr=0x3C | ✅ |
| Webcam CSI (IMX219) | /dev/video0 su Raspberry | ✅ |

### Librerie PlatformIO su Raspberry (pre-installate)
- Adafruit_SSD1306, Adafruit-GFX-Library, Adafruit_BusIO

---

## DUE MODALITÀ DI RUN

### 1. Tool Agent (NUOVO — preferito)
`agent/tool_agent.py` — loop ReAct dove MI50 decide autonomamente:
- Quali tools chiamare e in che ordine
- Se e quando usare la webcam
- Quanti tentativi di patch fare
- Quando salvare nel DB

```bash
python agent/tool_agent.py "task" --fqbn esp32:esp32:esp32
```

**Tools disponibili al modello:**
- `list_tools` / `get_tool(name)` — discovery lazy
- `plan_task` / `plan_functions` — orchestrator MI50
- `generate_globals` / `generate_function` — generator M40
- `compile` — arduino-cli con fix automatici
- `analyze_errors` / `patch_code` — MI50 analisi + M40 patch
- `upload_and_read` — PlatformIO + seriale
- `grab_frames` — webcam CSI
- `evaluate_text` / `evaluate_visual` — evaluator MI50
- `search_kb` / `save_to_kb` — knowledge base

**Pattern lazy tool loading:**
Il system prompt dice solo che i tools esistono. Il modello chiama
`list_tools` quando vuole la lista compatta, `get_tool(nome)` per i dettagli.
Il codice non gira mai nel contesto — solo risultati sintetici.

### 2. Loop classico (mantenuto per compatibilità)
`agent/loop.py` — flusso sequenziale hardcoded (Analyst→Orchestrator→Generator→
Compiler→Upload→Evaluator→Learner). Ancora funzionante, utile per debug.

```bash
python agent/loop.py "task" --fqbn esp32:esp32:esp32
```

---

## DASHBOARD (porta 7700)

```bash
# Avvio stabile
nohup python3 -c "
import sys; sys.path.insert(0, '.')
import agent.dashboard as d, time
d.start()
while True: time.sleep(60)
" > /tmp/dashboard.log 2>&1 &
```

**Funzionalità:**
- 3 colonne: MI50 output, M40 output, Webcam frames
- **Taskbar** in basso: textarea task + select FQBN + Start/Stop
  - Start: pulisce tutto e avvia tool_agent.py nel venv corretto
  - Stop: ferma il processo
  - Stato agente polling ogni 2s, Start/Stop si abilitano di conseguenza
- **📷 Scatta**: cattura frame dalla webcam del Raspberry per posizionamento
- **🗑**: svuota cache frame (disco + UI + history SSE)
- Thread non-daemon: la dashboard rimane viva dopo la fine del task
- Frame persistenti su disco: `workspace/.frames_cache.json`

---

## COMPONENTI E FILE CHIAVE

```
agent/
  tool_agent.py       ← NUOVO: loop ReAct con tool calling
  loop.py             ← flusso classico (mantenuto)
  orchestrator.py     ← plan_task, plan_functions, analyze_errors (MI50)
  generator.py        ← generate_globals, generate_function, patch_code (M40)
  compiler.py         ← compile_sketch, fix_known_includes, fix_known_api_errors
  evaluator.py        ← evaluate, evaluate_visual
  analyst.py          ← search KB simili
  learner.py          ← salva snippet nel DB
  notebook.py         ← taccuino operativo, assembla .ino
  grab.py             ← grab_now: cattura frame webcam via SSH
  remote_uploader.py  ← upload PlatformIO, seriale, check librerie
  dashboard.py        ← Flask SSE porta 7700
  mi50_client.py      ← client HTTP per MI50
  mi50_server.py      ← server Flask per Qwen3.5-9B su ROCm
  m40_client.py       ← client HTTP per M40 (llama-server)

docker/
  Dockerfile.mi50     ← ROCm 6.2 + PyTorch + torchvision + causal-conv1d
  run_mi50.sh         ← avvia container MI50

tools/
  lista.json          ← indice compatto (nome + scopo 1 riga)
  compiler.json       ← schema dettagliato tool compiler
  grab.json           ← schema tool grab_now
  evaluator.json      ← schema tool evaluator
  orchestrator.json   ← schema tool orchestrator
  generator.json      ← schema tool generator
  remote_uploader.json
  knowledge.json
  notebook.json
  analyst.json
  learner.json
  dashboard.json
```

---

## FIX APPLICATI (sessioni recenti)

### Thinking abilitato ovunque
- Rimosso `/no_think` da tutti i prompt (analyst, orchestrator, generator, evaluator, learner)
- MI50 ragiona prima di rispondere → meno allucinazioni sugli errori

### fix_known_api_errors() in compiler.py
- `display.textWidth()` non esiste → corretto in `getTextBounds` con 7 argomenti
- `display.miaFunzione()` → `miaFunzione()` (funzioni utente non sono metodi Adafruit)
- `getTextBounds` con tipi sbagliati → corretti a `int16_t x1,y1; uint16_t tw,th`

### vcap_frames forzato in loop.py
- Se orchestrator restituisce 0 ma task ha parole chiave display/OLED/TFT → forza 3

### evaluate_visual migliorato
- `enable_thinking=False` nel processor visivo (5 min invece di 30)
- Filtro `mm_token_type_ids` da `model.generate()` (kwargs non supportati)
- Prompt: "guarda le immagini, non analizzare il codice"
- Criteri lenient: non penalizza angolo webcam, riflessi, luminosità

### torchvision nel Docker MI50
- `pip install torchvision==0.20.1 --index-url .../rocm6.2`
- Richiesto da Qwen3.5-VL per il processor visivo

### Dashboard
- Thread non-daemon (sopravvive alla fine del task)
- Endpoint `/grab_test`, `/run_task`, `/stop_task`, `/agent_status`, `/clear_frames`
- Start: pulisce tutto + avvia nel venv corretto (`.venv/bin/python3`)
- Stop: disabilita Start, abilita Stop e viceversa

---

## COMANDI RAPIDI

```bash
# Avvio server (SEMPRE usare questo)
cd /home/lele/codex-openai/programmatore_di_arduini && source .venv/bin/activate
bash agent/start_servers.sh

# Stato server
curl -s localhost:11434/health && curl -s localhost:11435/health

# Tool Agent (nuovo)
python agent/tool_agent.py "task" --fqbn esp32:esp32:esp32

# Loop classico
python agent/loop.py "task" --fqbn esp32:esp32:esp32

# Solo compilazione
python agent/loop.py "task" --fqbn esp32:esp32:esp32 --no-upload

# Kill processi stuck sul Raspberry
ssh lele@192.168.1.167 "pkill -f esptool; pkill -f 'pio run'"

# Ultimo log
tail -f /tmp/tool_agent.log

# Restart MI50
docker stop mi50-server && docker rm mi50-server && bash docker/run_mi50.sh

# Knowledge base
sqlite3 knowledge/arduino_agent.db "SELECT task_description, board, created_at FROM snippets ORDER BY created_at DESC LIMIT 5;"
```

---

## TODO PRIORITARI

1. **Test completo tool_agent** — astronave OLED in corso, verificare che il modello
   usi grab_frames autonomamente senza hint espliciti nel task
2. **Context management nel tool_agent** — con 6144 token max su MI50, dopo ~15 step
   la conversazione potrebbe saturarsi. Aggiungere summarizzazione se messages > 10
3. **tools/grab.json aggiornato** — verificare che lo schema rispecchi l'API attuale
   di grab_now (ritorna dict con frame_paths, non lista diretta)
4. **Webcam posizionamento** — il foro di fissaggio del display OLED era visibile
   nella webcam; riorientare fisicamente la cam prima del prossimo test visivo
