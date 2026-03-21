# Agent_ino — Programmatore Autonomo di ESP32

> Agente che riceve un task in linguaggio naturale e produce codice Arduino funzionante —
> pianificazione, generazione, compilazione, upload fisico e valutazione (seriale + visione).
> **Stato: 2026-03-21 — Boids con Predatore in run, 100% autonomia raggiunta.**

---

## Cos'è

Un sistema multi-agente che usa due GPU locali con ruoli separati:

| GPU | Modello | Ruolo |
|-----|---------|-------|
| **MI50** (AMD, 32 GB, ROCm) | Qwen3.5-9B bfloat16 | Planning, analisi errori, valutazione visiva |
| **M40** (NVIDIA Tesla, 11.5 GB, CUDA) | Qwen3.5-9B Q5_K_M GGUF | Generazione codice veloce, Visual Judge |

**Hardware fisico remoto:**
- Raspberry Pi 3B (`192.168.1.167`) — flash e lettura seriale via SSH
- ESP32 NodeMCU — `/dev/ttyUSB0` sul Raspberry, baud 115200
- Webcam CSI IMX219 — `/dev/video0` sul Raspberry, valutazione visiva

---

## Risultati — Esperimenti completati (2026-03-21)

Il sistema ha eseguito una progressione di task con complessità crescente, misurando l'autonomia:

| Task | Errori compilazione | Patch | Intervento manuale | Autonomia |
|------|--------------------|----|-------------------|-----------|
| Pallina singola (T1) | molti | molte | sì | bassa |
| Tre palline (T4) | alcuni | alcune | sì | media |
| Muretto v1 (AABB, game state) | 0 | 0 | sì (bug logici) | ~60% |
| Muretto v2 (fix upfront) | 0 | 0 | sì (bug logici) | ~65% |
| Attrattore gravitazionale | 8+26 | 2 | sì (loop() mancante + 6 bug) | ~70% |
| **Boids — stormo emergente** | **0** | **0** | **zero** | **100%** ✅ |
| Boids + Predatore | in corso... | — | — | — |

### Boids — prima run 100% autonoma

8 agenti su OLED 128×64, algoritmo Reynolds 1986 (Separazione + Allineamento + Coesione).
156 righe generate da M40, compilazione al primo tentativo, zero patch, zero intervento umano.
Output: `CLUSTER:8` costante — stormo compatto che vola per lo schermo cambiando forma.

```
Frame 0 → stormo in alto-sinistra (forma "L")
Frame 1 → stormo al centro (forma compatta verticale)
Frame 2 → stormo centro-destra (curva verticale)
Viaggio: ~60px in 4s con comportamento emergente visibile
```

### Perché è importante

Il salto qualitativo da Attrattore (70%) a Boids (100%) è spiegato da:
1. **Task description ultra-dettagliata** — pseudocodice funzione per funzione, tipi esatti
2. **Knowledge Base con lessons** — 5 lessons iniettate automaticamente nel contesto MI50
3. **Pattern noti espliciti** — `abs()` per bordi, `float &dx` per by-ref, `dist_boids(i,j)`

---

## Architettura — ReAct Loop (tool_agent.py)

L'entry point principale è `agent/tool_agent.py` — un loop ReAct (Reason + Act) dove
MI50 pianifica e chiama tool, M40 genera codice in parallelo.

```
Task (linguaggio naturale)
    │
    ▼
[MI50 — ReAct Agent]
    ├── plan_task()          → approccio, librerie, key_points
    ├── plan_functions()     → 10-13 funzioni con firma, compito, dipendenze, pseudocodice
    ├── generate_globals()   → M40 genera globals/include/define/struct
    ├── generate_all_functions() → M40 genera tutte le funzioni IN PARALLELO
    ├── compile_sketch()     → arduino-cli, se errori: patch_code() → ricompila (max 3×)
    ├── upload_and_read()    → PlatformIO via Raspberry SSH → output seriale
    ├── grab_frames()        → 3 frame webcam dal Raspberry
    ├── evaluate_visual()    → pipeline: serial-first + PIL + M40 VisualJudge + MI50-vision
    └── save_to_kb()         → pattern estratti → ChromaDB + SQLite
```

**Checkpoint/Resume**: ogni step è serializzato in `checkpoint.json`.
Se la run crasha o viene interrotta: `python agent/tool_agent.py --resume <run_dir>`.

---

## Pipeline di valutazione visiva (Occhio Bionico)

Novità chiave di questa sessione — valutazione completamente locale, senza cloud vision:

```
Step 0 — Serial-first:
  HIT/BREAK/CLUSTER nel serial output → success=True immediato, zero analisi visiva

Step 1 — PIL pixel analysis:
  Per ogni frame: white_ratio, blob count, blob sizes, animazione (diff tra frame)

Step 2 — M40 VisualJudge (testo, no immagini):
  Riceve descrizione testuale strutturata + task description
  → "success": true/false + motivazione

Step 3 — MI50-vision fallback (solo se M40 non convince):
  Analisi diretta dei frame con modello multimodale
```

**Preprocessing frame** (3 versioni per ogni frame):
- Crop centrale 60% + upscale 2× + contrasto 2×
- Grayscale + contrasto 3× + threshold >160 (B&W netto)
- Edge detection (Laplacian) + contrasto 3× + upscale 2×

---

## Avvio rapido

```bash
cd /home/lele/codex-openai/programmatore_di_arduini
source .venv/bin/activate

# 1. Avvia i server GPU (SEMPRE usare start_servers.sh)
bash agent/start_servers.sh

# 2. Verifica
curl -s localhost:11434/health   # MI50 → {"status":"ok","device":"cuda"}
curl -s localhost:11435/health   # M40  → {"status":"ok"}
docker ps | grep memoria_ai      # memory server → Up

# 3. Lancia un task
python agent/tool_agent.py "Simulazione Boids su OLED SSD1306 128x64" \
    --fqbn esp32:esp32:esp32

# 4. Dashboard real-time
# http://localhost:7700  (si apre automaticamente)

# 5. Resume se interrotto
python agent/tool_agent.py --resume logs/runs/<run_dir>
```

---

## Struttura cartelle

```
Agent_ino/
├── README.md                    ← questo file
├── STATO.md                     ← stato corrente (leggi prima di lavorare)
├── CLAUDE.md                    ← istruzioni per Claude Code
├── PREFLIGHT.md                 ← checklist 9 step pre-run (eseguila sempre)
├── TODO.md                      ← roadmap esperimenti futuri
│
├── agent/
│   ├── tool_agent.py            ← entry point: ReAct loop MI50, genera con M40
│   ├── start_servers.sh         ← avvio sicuro MI50 + M40 (gestisce VRAM e porta)
│   ├── mi50_server.py           ← server Flask: Qwen3.5-9B bfloat16 ROCm (porta 11434)
│   ├── mi50_client.py           ← client MI50 con _TokenBatcher streaming SSE
│   ├── m40_client.py            ← client M40 llama-server (porta 11435)
│   ├── orchestrator.py          ← MI50: parsing ReAct, _safe_json, _truncate_to_first_action
│   ├── generator.py             ← M40: generate_globals/all_functions/patch
│   ├── compiler.py              ← arduino-cli wrapper + fix_known_includes + parser errori
│   ├── evaluator.py             ← pipeline: serial-first + PIL blob + M40 judge + MI50 vision
│   ├── grab_tool.py             ← script eseguito SUL Raspberry (awbgains, contrast, ev)
│   ├── learner.py               ← MI50: estrazione pattern → KB
│   ├── remote_uploader.py       ← PlatformIO via Raspberry SSH
│   ├── dashboard.py             ← dashboard SSE porta 7700, frame persistenti su disco
│   └── memoria_ai_client.py     ← client memory server porta 7701 (shared Claude+Codex)
│
├── knowledge/
│   ├── db.py                    ← SQLite CRUD: snippets, libraries, errors, runs
│   ├── semantic.py              ← ChromaDB: ricerca semantica (all-MiniLM-L6-v2)
│   ├── arduino_agent.db         ← database SQLite con lessons
│   └── chroma/                  ← ChromaDB vector store (escluso da git)
│
├── docker/
│   ├── Dockerfile.mi50          ← MI50: ROCm + HuggingFace + torchvision 0.20.1
│   └── run_mi50.sh              ← avvia container MI50 con GPU passthrough
│
├── docs/                        ← LEZIONI — storia completa degli esperimenti
│   ├── lezione_boids_completa.md      ← Boids stormo emergente, 100% autonomia, frame webcam
│   ├── lezione_predatore_completa.md  ← Boids + Predatore (in corso)
│   ├── lezione_attrattore.md          ← Attrattore gravitazionale, 7 bug trovati/risolti
│   ├── lezione_boids.md               ← Specifica tecnica task Boids
│   ├── lezione_muretto.md             ← Muretto v1: collision AABB, game state
│   ├── lezione_muretto2.md            ← Muretto v2: task description upfront
│   ├── lezione_occhio_bionico.md      ← Implementazione pipeline visiva
│   ├── lezione_sistema_lessons.md     ← Primo test KB lessons automatiche
│   ├── lezione_3palline.md            ← Tre palline rimbalzanti
│   └── lezione_3palline_TENTATIVO1_FALLITO.md
│
├── logs/                         ← run archiviate (escluse da git — troppo pesanti)
│   └── runs/<timestamp>_<task>/
│       ├── run.log              ← log completo step by step
│       ├── checkpoint.json      ← stato serializzato per resume
│       ├── plan.json            ← piano MI50 (plan_task + plan_functions)
│       ├── code_v*.ino          ← codice per ogni versione generata/patchata
│       ├── serial_output.txt    ← output seriale ESP32
│       ├── frame_*.jpg          ← frame webcam originali
│       └── proc_f*_*.jpg        ← frame preprocessati (crop, thresh, edge)
│
└── boards/ / bin/ / tools/ / libraries/
```

---

## Knowledge Base

**Lessons salvate automaticamente** dopo ogni run riuscita. Attualmente:

| Lesson | Contenuto |
|--------|-----------|
| OLED SSD1306 | Costruttore `-1` come rst_pin, `Wire.begin(21,22)` esplicito |
| Fisica OLED | `vx` come px/frame (1.5–3.0), NON `vx*dt` |
| Bordi abs() | Pattern `if(x<R){x=R; vx=abs(vx);}` — direzione garantita |
| AABB collision | 4 check separati, NON `abs(ball.x - brick.x) < R + W` |
| Boids/stormo | sep=1.5, ali=0.8, coh=0.6, RADIUS=25px, float &dx by-ref |
| M40 patcher | Dopo ogni patch verificare che `setup()` e `loop()` esistano |
| Attrattore | `vx += (dx/dist)*0.06`, clamp max 3.0, abs() per bordi attrattore |

KB interrogata automaticamente prima di ogni planning — MI50 riceve le 5 lessons più rilevanti.

---

## Memory Server (porta 7701)

Memoria condivisa tra Claude e Codex — persiste tra sessioni, accessibile a tutti gli agenti:

```bash
docker start memoria_ai_server

# Salva
python -c "from agent.memoria_ai_client import remember; remember('testo', 'lesson', ['tag'])"

# Recall
python -c "from agent.memoria_ai_client import recall; [print(r['snippet']) for r in recall('boids oled')]"
```

---

## Bug critici risolti (storia)

| # | Bug | Fix |
|---|-----|-----|
| 1 | Costruttore SSD1306: 4° param era I2C addr | Sempre `-1` (rst_pin) |
| 2 | M40 patcher elimina `loop()` nel multi-round | Verifica post-patch obbligatoria |
| 3 | `vx*dt` con dt=0.016 → palline ferme | `vx` in px/frame direttamente |
| 4 | AABB falsi positivi ai bordi dei mattoncini | 4 check separati |
| 5 | PlatformIO fallisce, arduino-cli passa | `loop()` mancante — linker più strict |
| 6 | Bordi senza `abs()` → palline incastrate | Pattern `abs(vx)` su tutti i bordi |
| 7 | evaluate_visual falso negativo | Pipeline serial-first → no visual se HIT/BREAK |
| 8 | VCAP port conflict upload/grab | Upload prima → 3s boot → grab_now() |
| 9 | Processi PIO stuck sul Raspberry | `pkill -f esptool; pkill -f 'pio run'` pre-upload |
| 10 | MI50 run-ahead hallucination | `_truncate_to_first_action()` tronca al primo JSON |

---

## Prossimi esperimenti (TODO.md)

```
→ Boids con Predatore (IN CORSO)    — seek/flee, dinamica predatore-preda
→ Boids v2 SPLIT/MERGE             — RADIUS=15px, pesi sep aumentati
→ Conway's Game of Life             — automa cellulare, paradigma discreto
→ Multi-predatore cooperante        — 2 predatori con Boids tra loro
→ Boids con ostacoli                — mattoncini fissi che gli agenti evitano
```

---

## Comandi utili

```bash
# Stato server
curl -s localhost:11434/health && curl -s localhost:11435/health

# Lancia task
python agent/tool_agent.py "task description" --fqbn esp32:esp32:esp32

# Resume run interrotta
python agent/tool_agent.py --resume logs/runs/<timestamp_task>/

# Kill stuck sul Pi
ssh lele@192.168.1.167 "pkill -f esptool; pkill -f 'pio run'"

# KB: ultimi snippet
sqlite3 knowledge/arduino_agent.db \
  "SELECT task_description, created_at FROM snippets ORDER BY created_at DESC LIMIT 5;"

# Restart MI50 (dopo reboot o OOM)
docker stop mi50-server && docker rm mi50-server && bash docker/run_mi50.sh
docker exec mi50-server pip install torchvision==0.20.1 \
  --index-url https://download.pytorch.org/whl/rocm6.2 -q

# Fix rete Raspberry
sudo dhcpcd eth0
```
