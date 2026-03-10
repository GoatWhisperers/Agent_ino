# Architettura tecnica — Programmatore di Arduini

Documentazione tecnica completa dei componenti, dei flussi di dati e delle interfacce.

---

## Panoramica

Il sistema è composto da due modelli LLM su GPU separate, un'infrastruttura di compilazione locale, un Raspberry Pi remoto per l'hardware fisico, e un database di conoscenza che cresce nel tempo.

```
┌─────────────────────────────────────────────────────────────────┐
│  Server principale (lele@server)                                │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │   MI50       │    │    M40       │    │  arduino-cli     │  │
│  │  AMD Vega20  │    │  NVIDIA M40  │    │  (locale)        │  │
│  │  32 GB VRAM  │    │  11.5 GB     │    │                  │  │
│  │  ROCm 6.2    │    │  CUDA sm_52  │    │  compila .ino    │  │
│  │  Qwen3.5-9B  │    │  Qwen3.5     │    │  produce .bin    │  │
│  │  (PyTorch)   │    │  9B-Q5_K_M   │    └──────────────────┘  │
│  │  porta 11434 │    │  porta 11435 │                           │
│  └──────────────┘    └──────────────┘                           │
│         │                   │                                   │
│         └─────────┬─────────┘                                   │
│                   │                                             │
│           loop.py (orchestratore Python)                        │
│                   │                                             │
│  ┌────────────────┴────────────────┐                            │
│  │  knowledge/                     │                            │
│  │  SQLite + ChromaDB              │                            │
│  └─────────────────────────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
              │ SSH/SCP
              ▼
┌─────────────────────────────────────────┐
│  Raspberry Pi 3B (192.168.1.167)        │
│                                         │
│  PlatformIO    grab_tool.py             │
│  esptool       /dev/video0 (webcam CSI) │
│      │                                  │
│      ▼                                  │
│  ESP32 via /dev/ttyUSB0                 │
└─────────────────────────────────────────┘
```

---

## Componenti — MI50

### `agent/mi50_server.py`

Server HTTP Flask persistente sulla porta `11434`. Carica Qwen3.5-9B in bfloat16 una volta sola e rimane in VRAM per tutta la sessione.

**Endpoint:**
- `GET /health` → `{"status": "ok"}`
- `POST /generate_stream` → SSE stream di token (`data: {"token": "..."}\n\n`, chiuso da `data: [DONE]\n\n`)
- `POST /generate_with_images` → risposta sincrona con visione multimodale

**Parametri `/generate_stream`:**
```json
{
  "messages": [{"role": "system|user|assistant", "content": "..."}],
  "max_new_tokens": 1024
}
```

**Variabili d'ambiente critiche (impostate all'avvio):**
```
HSA_OVERRIDE_GFX_VERSION=9.0.6    ← architettura reale MI50 (Vega20/gfx906)
HIP_VISIBLE_DEVICES=0
HSA_ENABLE_SDMA=0
PYTORCH_HIP_ALLOC_CONF=max_split_size_mb:128,...,expandable_segments:True
HF_HOME=/mnt/raid0/hf_cache
```

**Limiti contesto:**
```python
MAX_INPUT_TOKENS = 6144   # input troncato prima della GPU
```
Calcolo: 18 GB modello + ~3 GB prefill a 6K tok = ~21 GB su 32 GB disponibili.

**Caricamento modello:**
```python
_model = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH,
    torch_dtype=torch.bfloat16,
    trust_remote_code=True,
    attn_implementation="eager",   # NO Triton, NO flash-attn (gfx906 non supporta)
).to("cuda")
```
MAI usare `device_map="auto"` o `low_cpu_mem_usage=True` su ROCm.

**Container Docker:**
Gira dentro `docker/Dockerfile.mi50` con GPU passthrough zero-overhead:
```bash
--device /dev/kfd --device /dev/dri --group-add video
```
Il modello è montato read-only da `/mnt/raid0/qwen3.5-9b`.

---

### `agent/mi50_client.py`

Singleton thread-safe. Connette al server, fa streaming, estrae thinking.

```python
client = MI50Client.get()
result = client.generate(messages, max_new_tokens=1024, label="Orchestrator")
# result = {"thinking": str, "response": str, "raw": str}

result = client.generate_with_images(messages, image_paths, label="Evaluator")
# stessa struttura
```

Durante lo streaming chiama automaticamente `dashboard.token("mi50", token)` per il dashboard real-time.

---

## Componenti — M40

### `agent/m40_client.py`

Client HTTP per llama-server. API OpenAI-compatible.

```python
client = M40Client()
result = client.generate(messages, max_tokens=512, label="Generator→setup")
# result = {"thinking": str, "response": str, "raw": str}
```

Durante lo streaming chiama `dashboard.token("m40", token)`.

**Server llama.cpp:**
```bash
/mnt/raid0/llama-cpp-m40/build_cuda/bin/llama-server \
    --model /mnt/raid0/models-gguf/Qwen3.5-9B-Q5_K_M.gguf \
    --host 0.0.0.0 --port 11435 \
    --ctx-size 16384 --n-gpu-layers 99 --threads 8
```

**Calcolo contesto M40:**
- Modello: ~6.5 GB
- KV cache a 16384 tok: ~2.3 GB (36 layer × 8 KV heads × 128 dim × 2 × 16K)
- Totale: ~8.8 GB su 11.5 GB disponibili → margine sicuro

---

## Strategia thinking

Qwen3.5 supporta thinking mode (`<think>...</think>`). Viene attivato selettivamente:
- **`/no_think`** su tutti i prompt di Analyst, Generator, Orchestrator — risposta diretta, 10-60 sec
- **Thinking attivo** solo sull'Evaluator — deve ragionare su output seriale/visivo ambiguo

Risparmio stimato per run: da ~45-60 min a ~20-30 min.

→ Documentazione dettagliata: `docs/thinking_strategy.md`

---

## Componenti — Agent

### `agent/notebook.py` — Notebook operativo

Taccuino strutturato per ogni task. Persiste su `workspace/current/<task>/notebook.json`.

**Struttura dati:**
```python
class Notebook:
    task: str
    board: str
    piano: list[str]          # key_points dall'Orchestrator
    dipendenze: list[str]     # librerie needed
    note_tecniche: list[str]  # vincoli concreti (pin, addr, baud)
    globals_hint: str         # suggerimento includes/defines per M40
    globals_code: str         # codice globals scritto da M40
    funzioni: list[dict]      # [{nome, firma, compito, dipende_da, stato, codice}]
    stato: str                # planning|generating|compiling|done|failed
    errori_visti: list[dict]  # [{errore, fix}] — M40 non li ripete
    log_fasi: list[dict]      # [{fase, risultato, ts}]
```

**Metodi chiave:**
- `set_plan(piano, dipendenze, note_tecniche)` — da Orchestrator fase 1
- `set_funzioni(globals_hint, funzioni)` — da Orchestrator fase 1b
- `funzioni_ordinate()` — topological sort, setup() prima, loop() ultima
- `context_for_globals()` — contesto compatto per M40 globals
- `context_for_function(nome)` — contesto per una singola funzione
- `assemble()` → `(code, line_map)` — assembla .ino finale
- `funzione_da_errore(line_map, error_line)` — attribuisce errore a funzione
- `save(path)` / `load(path)` — persistenza JSON

→ Documentazione dettagliata: `docs/notebook.md`

---

### `agent/orchestrator.py` — Orchestrator (MI50)

Usa MI50 per planning strutturato. Output sempre JSON.

**`plan_task(task, context, mode)`:**
```json
{
  "approach": "I2C su pin 21/22, SSD1306 addr 0x3C",
  "libraries_needed": ["Adafruit_SSD1306", "Adafruit-GFX-Library"],
  "key_points": ["Wire.begin(21,22)", "display.begin(...)"],
  "note_tecniche": ["SDA=GPIO21 SCL=GPIO22", "I2C addr=0x3C"],
  "vcap_frames": 3,
  "vcap_interval_ms": 2000
}
```

**`plan_functions(task, context, mode)`:**
```json
{
  "globals_hint": "#include <Wire.h>\nAdafruit_SSD1306 display(128,64,&Wire);",
  "funzioni": [
    {"nome":"setup","firma":"void setup()","compito":"Wire.begin(21,22)...","dipende_da":[]},
    {"nome":"readTemp","firma":"float readTemp()","compito":"...","dipende_da":[]},
    {"nome":"loop","firma":"void loop()","compito":"...","dipende_da":["readTemp"]}
  ]
}
```

**`analyze_errors(code, errors)`:**
```json
{
  "analysis": "Il metodo display.clearDisplay() richiede header non incluso",
  "fix_hints": ["Aggiungere #include <Adafruit_GFX.h>"]
}
```

Il parsing JSON usa `_safe_json()` che prova: blocco ` ```json ` → testo intero → tutti i candidati `{…}` dall'ultimo al primo (il modello mette spesso il JSON alla fine del thinking).

---

### `agent/generator.py` — Generator (M40)

Genera codice Arduino. Tre modalità principali:

**`generate_globals(nb)`** — sezione globale del .ino:
- Solo `#include`, `#define`, oggetti globali, variabili
- Contesto: task, board, note_tecniche, lista firme future
- max_tokens: 512

**`generate_function(nome, nb)`** — una funzione alla volta:
- Contesto: globals scritti, firme di tutte le funzioni, corpo delle dipendenze, compito
- max_tokens: 512
- Il contesto è compatto per design — M40 non ha bisogno di vedere tutto

**`generate_code(task, context, ...)`** — generazione monolitica (fallback):
- Usato se `plan_functions()` torna vuoto
- max_tokens: 2048

**`patch_code(code, errors, analysis)`** — correzione errori:
- Riceve codice + lista errori strutturata + analisi di MI50
- Produce codice corretto completo
- max_tokens: 2048

**`_extract_code(raw)`** — pulizia output LLM:
1. Rimuove `<think>...</think>`
2. Cerca fence ` ```cpp / ```arduino / ```c++ / ```c `
3. Cerca qualsiasi fence ` ``` `
4. Fallback: testo intero ripulito

---

### `agent/loop.py` — Loop principale

Entry point. Coordina tutte le fasi in sequenza.

**Fasi:**

| Fase | Funzione | Modello | Descrizione |
|------|----------|---------|-------------|
| 0 | `_phase_analyst()` | MI50 | cerca codice simile, analizza progetto |
| 1 | `_phase_plan()` | MI50 | planning + inizializza Notebook |
| 2 | `_phase_generate()` | M40 | genera codice (per-funzione o monolitico) |
| 3 | `_phase_compile_loop()` | arduino-cli + MI50 + M40 | compila e corregge |
| 4 | `_phase_upload_serial_remote()` | Raspberry Pi | flash + serial ± webcam |
| 5 | `_phase_evaluate()` / `_phase_evaluate_visual()` | MI50 | valuta risultato |
| 6 | `_phase_learn()` | MI50 | estrae pattern → DB |

**Costanti:**
```python
MAX_COMPILE_ATTEMPTS = 5    # tentativi compilazione
MAX_EVAL_ATTEMPTS    = 3    # cicli upload+eval
SERIAL_READ_SECONDS  = 10   # lettura output seriale
```

**Rilevamento scheda:**
- `esp32` nel FQBN → upload remoto via Raspberry Pi
- altro → upload locale via arduino-cli + porta seriale

---

### `agent/compiler.py` — Compiler

Wrapper per `arduino-cli`. Compila e torna errori strutturati.

**Nota:** la regex di parsing include `fatal error` oltre a `error` e `warning`.
arduino-cli per ESP32 produce `fatal error:` (es. header mancante) — senza questo
match il compilatore riportava 0 errori anche a fronte di fallimento, rendendo il
loop di fix completamente cieco.

```python
result = compile_sketch(sketch_dir, fqbn="esp32:esp32:esp32")
# result = {
#   "success": bool,
#   "errors":  [{"line": int, "type": "error|warning", "message": str}],
#   "warnings": [...],
#   "stdout": str, "stderr": str
# }
```

Usa `bin/arduino-cli` locale al progetto. Librerie installate localmente in `~/.arduino15/`.

---

### `agent/remote_uploader.py` — Remote Uploader

Upload via Raspberry Pi usando PlatformIO.

**Flusso:**
1. `setup_pio_project(task, ino_code, libraries)` — crea dir PlatformIO sul Raspberry via SSH, scrive `src/main.cpp` e `platformio.ini`
2. `compile_pio(project_dir)` — esegue `pio run` sul Raspberry
3. `upload_pio(project_dir, port)` — esegue `pio run -t upload`
4. `read_serial_remote(port, baud, duration_sec)` — legge seriale con Python su Raspberry

**`platformio.ini` generato:**
```ini
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
upload_port = /dev/ttyUSB0
monitor_speed = 115200
lib_extra_dirs = ~/.platformio/lib
```

**Librerie PlatformIO pre-installate sul Raspberry:**
- `Adafruit_SSD1306`, `Adafruit-GFX-Library`, `Adafruit_BusIO`
- Path: `~/.platformio/lib/` su Raspberry

---

### `agent/grab.py` — Grab webcam

Cattura frame dalla webcam CSI sul Raspberry Pi.

**Modalità 1 — grab immediato:**
```python
paths = grab.grab_now(n_frames=2, interval_ms=500)
# → ["/tmp/grab_local_xxx/frame_0.jpg", "..."]
```

**Modalità 2 — grab seriale (triggered dall'ESP32):**
```python
session_id = grab.start_serial_grab(port="/dev/ttyUSB0", baud=115200, timeout_sec=30)
# ...upload firmware...
result = grab.collect_grab(session_id)
# result = {"n_frames": 3, "frame_paths": [...], "lines": [...], "serial_output": str}
grab.cleanup_grab(session_id)
```

**Protocollo VCAP (segnali seriali dall'ESP32):**
```
VCAP_READY          ← ESP32 pronto, avvia cattura continua
VCAP_START N T      ← cattura N frame ogni T ms
VCAP_NOW <label>    ← cattura un frame su evento
```

**Storage:**
- Sul Raspberry: `/dev/shm/grab_<session>/` — RAM, zero scritture SD
- Sul server: `/tmp/grab_local_<session>/` — temporaneo, rimosso da `cleanup_grab()`

→ Documentazione dettagliata: `docs/camera_grab.md`

---

### `agent/dashboard.py` — Dashboard SSE

Dashboard web real-time su porta `7700`.

Avviato automaticamente da `loop.py` con `dashboard.start()`. Thread daemon, zero impatto sulle performance.

**API pubblica:**
```python
dashboard.start()                           # avvia Flask in thread daemon
dashboard.task_start(task, board)           # nuovo task
dashboard.phase(name, detail)               # cambio fase
dashboard.token(source, text)               # token da MI50 o M40
dashboard.func_start(nome)                  # M40 inizia una funzione
dashboard.func_done(nome, righe)            # M40 finisce una funzione
dashboard.compile_result(ok, errors, n)     # risultato compilazione
dashboard.serial_output(lines)              # output seriale
dashboard.frame(path, label)                # frame webcam (carica e invia base64)
dashboard.notebook_update(summary, progress)
dashboard.run_end(success, reason)
```

Tutti i metodi sono no-op se `dashboard.start()` non è stato chiamato (`_active = False`).

→ Documentazione dettagliata: `docs/dashboard.md`

---

## Knowledge Base

### Schema SQLite (`knowledge/arduino_agent.db`)

```sql
CREATE TABLE libraries (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    description TEXT,
    install_cmd TEXT,
    source TEXT,          -- "manual" | "learned"
    created_at TEXT
);

CREATE TABLE snippets (
    id TEXT PRIMARY KEY,
    task_description TEXT,
    code TEXT,
    board TEXT,
    libraries TEXT,       -- JSON array
    tags TEXT,            -- JSON array
    success_count INT DEFAULT 0,
    created_at TEXT
);

CREATE TABLE errors (
    id TEXT PRIMARY KEY,
    pattern TEXT UNIQUE,
    fix_description TEXT,
    occurrence_count INT DEFAULT 0,
    created_at TEXT
);

CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    task TEXT,
    mode TEXT,
    success INT,
    iterations INT,
    final_code TEXT,
    serial_output TEXT,
    created_at TEXT
);
```

### ChromaDB (`knowledge/chroma/`)

Collezione `arduino_snippets`. Embedding con `all-MiniLM-L6-v2` (384 dim).
- Document: `task_description + "\n" + code[:500]`
- Metadata: `{snippet_id, board, tags}`
- Query: `get_context_for_task(task)` → top-5 snippet per cosine similarity

---

## Gestione VRAM

### Regola fondamentale
Una GPU, un modello, un processo. Sempre.

`start_servers.sh` prima di avviare fa kill di **tutti** i processi GPU:
```bash
ps aux | grep -E "mi50_server\.py|steering_server\.py|llama-server" | ...kill -9
```

### MI50 — budget VRAM

| Componente | VRAM |
|-----------|------|
| Modello bfloat16 (~9B params) | ~18 GB |
| Overhead PyTorch (grad buffers, etc.) | ~1 GB |
| Picco prefill a 6144 token | ~3 GB |
| **Totale picco** | **~22 GB** |
| **Disponibile** | **32 GB** |
| **Margine** | **~10 GB** ✓ |

### M40 — budget VRAM

| Componente | VRAM |
|-----------|------|
| Modello Q5_K_M (~9B params) | ~6.5 GB |
| KV cache a 16384 tok | ~2.3 GB |
| Overhead llama.cpp | ~0.3 GB |
| **Totale** | **~9.1 GB** |
| **Disponibile** | **11.5 GB** |
| **Margine** | **~2.4 GB** ✓ |

---

## Docker MI50

### Perché Docker
- Isolamento dell'ambiente ROCm (librerie, versioni, env vars)
- GPU passthrough è **trasparente** — zero overhead rispetto a bare metal
- `causal_conv1d` richiede una build HIP specifica (fake `amdgpu-arch` per gfx906)

### Struttura `docker/Dockerfile.mi50`
```dockerfile
FROM rocm/dev-ubuntu-22.04:6.2-complete
# PyTorch 2.5.1+rocm6.2
# causal_conv1d con fake amdgpu-arch (trick per gfx906)
# transformers >= 4.47.0
# flask, pyserial, requests
ENV HSA_OVERRIDE_GFX_VERSION=9.0.6
```

### `docker/run_mi50.sh`
```bash
docker run --rm -d \
    --device /dev/kfd --device /dev/dri --group-add video \
    -v /mnt/raid0/qwen3.5-9b:/mnt/raid0/qwen3.5-9b:ro \
    -v /mnt/raid0/hf_cache:/mnt/raid0/hf_cache \
    -p 11434:11434 \
    --name mi50-server \
    mi50-server:latest
```

### Rebuild (solo se Dockerfile cambia)
```bash
docker build -f docker/Dockerfile.mi50 -t mi50-server . 2>&1 | tee /tmp/build.log
# ~20-30 min (PyTorch 4 GB dal layer cache se disponibile)
```

### Pulizia cache Docker (se disco pieno)
```bash
docker container prune -f && docker image prune -f
# libera ~50-130 GB di layer intermedi
```

---

## Schede supportate

| Board | FQBN | Baud | Uploader |
|-------|------|------|----------|
| Arduino Uno | `arduino:avr:uno` | 9600 | locale (avr-dude) |
| Arduino Mega | `arduino:avr:mega` | 9600 | locale |
| ESP32 NodeMCU | `esp32:esp32:esp32` | 115200 | remoto (Raspberry Pi) |
| NodeMCU 1.0 | `esp8266:esp8266:nodemcuv2` | 115200 | locale |

Per ESP32: il rilevamento avviene in automatico in `loop.py` — se `esp32` è nel FQBN si usa il flusso remoto Raspberry Pi.

---

## Modifica del sistema

### Aggiungere una nuova fase
1. Implementare la funzione `_phase_xxx()` in `loop.py`
2. Chiamarla nel flusso principale di `run()`
3. Aggiungere `_write_event(log_fh, "xxx", ...)` per il log
4. Aggiungere `dashboard.phase("xxx")` per il dashboard

### Aggiungere un nuovo modello
1. Creare `agent/nuovo_client.py` con metodo `generate()` compatibile
2. Assicurarsi che ritorni `{"thinking": str, "response": str, "raw": str}`
3. Aggiungere `dashboard.token("nuovo", token)` nello streaming loop

### Aggiungere un prompt
I prompt di sistema sono stringhe costanti in cima ai rispettivi file (`orchestrator.py`, `generator.py`, etc.). Modificarli direttamente. Il formato `/no_think` in testa al prompt sopprime il thinking di Qwen3.5 per risposte JSON (più veloci e parsabili).
