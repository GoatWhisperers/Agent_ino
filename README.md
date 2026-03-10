# Programmatore di Arduini

Agente autonomo che riceve un task in linguaggio naturale e produce codice Arduino funzionante — dalla pianificazione alla generazione, compilazione, upload sulla scheda fisica e valutazione del risultato (testo + visione).

**Due GPU, ruoli separati:**
- **MI50** (AMD, 32 GB VRAM, ROCm) — cervello: planning, analisi errori, valutazione
- **M40** (NVIDIA Tesla, 11.5 GB VRAM, CUDA) — mani: generazione codice veloce

**Hardware fisico remoto:**
- Raspberry Pi 3B (`192.168.1.167`) — fa flash e lettura seriale via SSH
- ESP32 NodeMCU — `/dev/ttyUSB0` sul Raspberry, baud 115200
- Webcam CSI IMX219 — `/dev/video0` sul Raspberry, per valutazione visiva

---

## Avvio rapido

```bash
cd /home/lele/codex-openai/programmatore_di_arduini
source .venv/bin/activate

# 1. Avvia i server GPU (se non già attivi)
bash agent/start_servers.sh

# 2. Verifica
curl -s localhost:11434/health   # MI50  → {"status":"ok"}
curl -s localhost:11435/health   # M40   → {"status":"ok"}

# 3. Lancia un task
python agent/loop.py "su display OLED SSD1306 mostra la temperatura" \
    --fqbn esp32:esp32:esp32

# Il dashboard si apre automaticamente su http://localhost:7700
```

### Opzioni CLI

| Opzione | Default | Descrizione |
|---------|---------|-------------|
| `task` | — | Descrizione in linguaggio naturale (obbligatorio) |
| `--mode` | `NEW` | `NEW` / `CONTINUE` / `MODIFY` |
| `--fqbn` | `arduino:avr:uno` | Fully Qualified Board Name scheda |
| `--port` | auto-detect | Porta seriale (es. `/dev/ttyUSB0`) |
| `--baud` | auto (115200 ESP32, 9600 AVR) | Baud rate |
| `--project` | generato dal task | Nome cartella in `workspace/current/` |
| `--no-upload` | `False` | Ferma dopo la compilazione |

---

## Flusso completo

```
Task (linguaggio naturale)
    │
    ▼
[FASE 0 — ANALYST — MI50]
    Cerca nel DB snippet simili → li analizza e produce contesto.
    CONTINUE: legge codice+notebook esistenti, capisce lo stato.
    MODIFY:   capisce cosa cambiare e cosa mantenere.
    │
    ▼
[FASE 1 — ORCHESTRATOR — MI50]
    plan_task()     → approccio, librerie, key_points, note_tecniche
                      vcap_frames (quanti frame webcam catturare)
    plan_functions() → lista funzioni con firma, compito, dipendenze
    Entrambi producono JSON → aggiornano il Notebook operativo.
    │
    ▼
[FASE 2 — GENERATOR — M40]  ← funzione per funzione
    generate_globals()     → #include, #define, variabili globali
    generate_function(f)   → una funzione alla volta, in ordine
                             topologico (dipendenze prima)
    assemble()             → .ino finale: globals + fwd decl + funzioni
    │
    ▼
[FASE 3 — COMPILER — arduino-cli]  ←─────────────────────┐
    Compila il .ino (max 5 tentativi).                     │
    Se errori:                                             │
      → ANALYZER (MI50): capisce la causa degli errori     │
      → PATCHER (M40): riscrive il codice corretto ────────┘
    │
    ▼ (se --no-upload: stop qui)
[FASE 4 — UPLOADER — PlatformIO via Raspberry Pi SSH]
    setup_pio_project() → crea progetto PlatformIO sul Raspberry
    compile_pio()       → compila con pio
    upload_pio()        → flasha sull'ESP32
    Oppure read_serial_remote() se vcap_frames == 0.
    Se vcap_frames > 0: start_serial_grab() → collects frames.
    │
    ▼
[FASE 5 — EVALUATOR — MI50]  ←──────────────────────────┐
    evaluate()        → confronta output seriale con task  │
    evaluate_visual() → analizza frame webcam + seriale    │
    Se non OK e tentativi rimasti: riscrive → ricompila ───┘
    │
    ▼ (solo se successo)
[FASE 6 — LEARNER — MI50]
    Estrae pattern riutilizzabili.
    Salva snippet + librerie + mappature errore→fix nel DB.
```

---

## Dashboard real-time

Quando `loop.py` parte, avvia automaticamente un dashboard web su **http://localhost:7700**.

- **Colonna MI50** — token live con thinking in grigio corsivo, risposte in bianco
- **Colonna M40** — badge per funzione (⚙ → ✓), codice generato in streaming
- **Colonna Webcam** — thumbnail frame catturati, clic per ingrandire
- **Header** — task corrente, fase attiva, timer, stato run

Il dashboard si riconnette automaticamente se la connessione cade.

→ Documentazione dettagliata: `docs/dashboard.md`

---

## Notebook operativo

Per ogni task, MI50 compila un taccuino strutturato (`notebook.json`) che contiene:
- Piano ad alto livello (key_points, note_tecniche, dipendenze)
- Lista funzioni con stato (pending → generating → done / error)
- Globals generati da M40
- Errori già visti → M40 non li ripete
- Log di tutte le fasi

M40 riceve solo la slice di contesto rilevante per la funzione che sta generando — niente OOM, massima qualità per funzione.

→ Documentazione dettagliata: `docs/notebook.md`

---

## Struttura cartelle

```
programmatore_di_arduini/
├── README.md                    ← questo file
├── STATO.md                     ← stato corrente del progetto (leggi per primo)
├── CLAUDE.md                    ← istruzioni per Claude (non rimuovere)
│
├── agent/
│   ├── loop.py                  ← entry point: coordina tutte le fasi
│   ├── start_servers.sh         ← avvio sicuro MI50 + M40 (SEMPRE usare questo)
│   │
│   ├── mi50_server.py           ← server HTTP Flask: Qwen3.5-9B su ROCm (porta 11434)
│   ├── mi50_client.py           ← client HTTP singleton per MI50
│   ├── m40_client.py            ← client HTTP per llama-server M40 (porta 11435)
│   │
│   ├── notebook.py              ← taccuino operativo per task (piano + funzioni + log)
│   ├── orchestrator.py          ← MI50: planning + analisi errori → JSON
│   ├── generator.py             ← M40: generate_globals/function/patch
│   ├── analyst.py               ← MI50: analisi codice simile/CONTINUE/MODIFY
│   ├── compiler.py              ← arduino-cli wrapper + parser errori strutturato
│   ├── remote_uploader.py       ← PlatformIO via Raspberry Pi SSH
│   ├── uploader.py              ← upload locale + lettura seriale (AVR)
│   ├── evaluator.py             ← MI50: valutazione output seriale + visiva
│   ├── learner.py               ← MI50: estrazione pattern → knowledge base
│   ├── grab.py                  ← cattura frame webcam Raspberry Pi
│   ├── grab_tool.py             ← script Python eseguito SUL Raspberry
│   └── dashboard.py             ← dashboard web SSE (porta 7700)
│
├── knowledge/
│   ├── db.py                    ← SQLite CRUD: snippets, libraries, errors, runs
│   ├── query_engine.py          ← query contesto per task
│   ├── semantic.py              ← ChromaDB: ricerca semantica snippet
│   ├── arduino_agent.db         ← database SQLite
│   ├── chroma/                  ← ChromaDB vector store (all-MiniLM-L6-v2)
│   └── docs/                    ← documentazione tecnica interna
│
├── boards/
│   ├── catalog.json             ← catalog schede supportate
│   └── pinouts/                 ← pinout per ogni scheda
│
├── workspace/
│   ├── current/                 ← progetti in lavorazione (una dir per task)
│   └── completed/               ← progetti riusciti (copiati qui dal Learner)
│
├── logs/
│   └── run_YYYYMMDD_HHMMSS.jsonl  ← log strutturato ogni run
│
├── docker/
│   ├── Dockerfile.mi50          ← immagine Docker per MI50 (ROCm + causal_conv1d)
│   └── run_mi50.sh              ← avvia container MI50 con GPU passthrough
│
├── docs/
│   ├── architettura.md          ← architettura tecnica completa
│   ├── notebook.md              ← notebook pattern + function-by-function generation
│   ├── dashboard.md             ← dashboard web real-time
│   ├── camera_grab.md           ← sistema grab frame webcam
│   └── webcam_raspberry.md      ← setup webcam CSI sul Raspberry
│
└── bin/
    └── arduino-cli              ← binario arduino-cli (locale al progetto)
```

---

## Log di una run

Ogni run produce `logs/run_YYYYMMDD_HHMMSS.jsonl`. Ogni riga è un evento JSON:

```jsonl
{"ts":"...","event":"run_start","task":"...","mode":"NEW","fqbn":"esp32:esp32:esp32"}
{"ts":"...","event":"orchestrator_plan","approach":"...","libraries":[],"thinking":"..."}
{"ts":"...","event":"orchestrator_func_plan","globals_hint":"...","n_funzioni":4}
{"ts":"...","event":"generator_globals","code_len":312}
{"ts":"...","event":"generator_func_setup","code_len":248,"thinking":"..."}
{"ts":"...","event":"generator_func_loop","code_len":156,"thinking":"..."}
{"ts":"...","event":"generator_assembled","code_len":1024,"n_funzioni":4}
{"ts":"...","event":"compile_attempt","attempt":1,"success":true,"errors":[],"warnings":[]}
{"ts":"...","event":"upload_result","success":true}
{"ts":"...","event":"serial_output","output":"...","lines":["READY","VCAP_READY"]}
{"ts":"...","event":"evaluation","success":true,"reason":"...","thinking":"..."}
{"ts":"...","event":"learner_output","snippet":{...},"libraries":[...]}
{"ts":"...","event":"run_end","success":true,"iterations":0}
```

Il campo `thinking` contiene il ragionamento interno di MI50 — non viene mai scartato.

---

## Knowledge Base

**SQLite** (`knowledge/arduino_agent.db`):
- `libraries` — librerie Arduino con descrizione e install_cmd
- `snippets` — codice funzionante per task/board/librerie
- `errors` — mappature pattern errore → fix confermato
- `runs` — storico run con esito

**ChromaDB** (`knowledge/chroma/`):
- Snippet indicizzati semanticamente con `all-MiniLM-L6-v2`
- Query in linguaggio naturale → snippet pertinenti

Aggiornato automaticamente dal Learner dopo ogni run riuscito. Non modificare manualmente.

---

## Limiti operativi

| Parametro | Valore | Note |
|-----------|--------|------|
| Tentativi compilazione | 5 | oltre: `success=False`, log salvato |
| Cicli valutazione | 3 | upload → serial → eval → rewrite |
| Context MI50 | 6144 token | troncato in `mi50_server.py` (OOM prevention) |
| Context M40 | 16384 token | `--ctx-size` in `start_servers.sh` |
| Lettura seriale | 10 sec | `SERIAL_READ_SECONDS` in `loop.py` |
| Tempo MI50 per risposta | 5-15 min | normale con thinking attivo |
| Velocità M40 | ~33 tok/s | |

---

## Comandi utili

```bash
# Avvio (SEMPRE da qui)
cd /home/lele/codex-openai/programmatore_di_arduini && source .venv/bin/activate
bash agent/start_servers.sh

# Stato server
curl -s localhost:11434/health && curl -s localhost:11435/health

# Run senza hardware
python agent/loop.py "task" --fqbn esp32:esp32:esp32 --no-upload

# Log live
tail -f logs/$(ls -t logs/ | head -1)

# Ultimi snippet nel DB
sqlite3 knowledge/arduino_agent.db \
  "SELECT task_description, board, created_at FROM snippets ORDER BY created_at DESC LIMIT 5;"

# Stato Raspberry
ssh lele@192.168.1.167 "ls /dev/ttyUSB* 2>/dev/null; fuser /dev/ttyUSB0 2>/dev/null && echo BUSY || echo FREE"

# Notebook dell'ultimo task
cat workspace/current/*/notebook.json | python3 -m json.tool | head -60

# Rebuild Docker MI50 (solo se necessario)
docker build -f docker/Dockerfile.mi50 -t mi50-server . 2>&1 | tee /tmp/mi50_docker_build.log
```
