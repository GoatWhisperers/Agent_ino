# STATO — Programmatore di Arduini

> Ultima modifica: 2026-03-11 sera

---

## DOVE SIAMO RIMASTI

Tool Agent funzionante: il processo parte, MI50 riceve il task e ragiona.
Il flusso dashboard→subprocess→MI50 funziona correttamente.
Non abbiamo ancora visto un task completato end-to-end con il nuovo tool agent.
Interrotto a metà del task "LED blink" — MI50 stava ancora pensando allo step 1.

---

## TODO PRIORITARI (per domani)

### [1] Verificare che MI50 risponda con JSON nel tool agent
- Il log mostra thinking in chiaro ("The user wants me to create...")
- Controllare se alla fine produce JSON valido oppure testo libero
- Se produce testo libero: stringere il system prompt, aggiungere esempio esplicito
- Tool: `tail -f /tmp/tool_agent.log` mentre gira

### [2] Test end-to-end task semplice
- Usare task banale (LED blink) per verificare tutto il flusso senza distrazioni
- Verificare che ogni step appaia in dashboard in real-time
- Solo dopo passare al task astronave OLED

### [3] Task astronave OLED con webcam
- Il task vero: astronave pixel-art che fluttua con seno su SSD1306
- Verificare che il modello chiami grab_frames autonomamente
- Verificare evaluate_visual con i frame catturati

### [4] Context saturation nel tool agent
- MI50 ha MAX_INPUT_TOKENS=6144, la conversazione cresce ad ogni step
- Aggiungere conteggio token e summarizzazione se messages > 10 step
- Alternativa: troncare la history tenendo solo system + ultimi N scambi

### [5] Webcam posizionamento
- Il foro di fissaggio del display era visibile nella cam → riposizionare fisicamente
- Usare "📷 Scatta" nella dashboard per verificare inquadratura prima di ogni run

---

## ARCHITETTURA CORRENTE

### Modelli
- **MI50** (AMD ROCm, Qwen3.5-9B bfloat16): reasoning + planning + valutazione → porta 11434
- **M40** (NVIDIA CUDA, Qwen3.5-9B Q5_K_M): code generation → porta 11435
- Thinking abilitato ovunque (rimosso /no_think da tutti i prompt)

### Hardware
- Raspberry Pi 3B: `lele@192.168.1.167` (pwd: pippopippo33$$)
- ESP32: `/dev/ttyUSB0` sul Raspberry, baud 115200
- OLED SSD1306 128x64: SDA=GPIO21, SCL=GPIO22, addr=0x3C
- Webcam CSI (IMX219): `/dev/video0` sul Raspberry

### Due modalità di run
1. **Tool Agent** (nuovo, preferito): `python agent/tool_agent.py "task"`
   - MI50 decide autonomamente quali tools chiamare e quando
   - Webcam usata solo se il modello lo decide
   - Eventi inviati alla dashboard via HTTP POST `/emit`
2. **Loop classico** (mantenuto): `python agent/loop.py "task"`
   - Flusso sequenziale hardcoded, stabile, utile per debug

### Dashboard (porta 7700)
- Taskbar Start/Stop in basso — avvia tool_agent.py nel venv corretto
- Start: pulisce tutto e parte; Stop: ferma il processo
- 📷 Scatta: cattura frame webcam per posizionamento
- 🗑: svuota cache frame
- Log subprocess in `/tmp/tool_agent.log`

---

## COMANDI RAPIDI

```bash
cd /home/lele/codex-openai/programmatore_di_arduini
source .venv/bin/activate

# Avvio server
bash agent/start_servers.sh

# Avvio dashboard
nohup python3 -c "
import sys; sys.path.insert(0, '.')
import agent.dashboard as d, time
d.start()
while True: time.sleep(60)
" > /tmp/dashboard.log 2>&1 &

# Tool agent diretto (senza dashboard)
python agent/tool_agent.py "task" --fqbn esp32:esp32:esp32

# Monitor log
tail -f /tmp/tool_agent.log

# Stato server
curl -s localhost:11434/health && curl -s localhost:11435/health

# Kill processi stuck sul Raspberry
ssh lele@192.168.1.167 "pkill -f esptool; pkill -f 'pio run'"

# Restart MI50 Docker
docker stop mi50-server && docker rm mi50-server && bash docker/run_mi50.sh
```

---

## FILE CHIAVE

```
agent/tool_agent.py      ← agente ReAct (NUOVO)
agent/loop.py            ← flusso classico
agent/dashboard.py       ← Flask SSE porta 7700 + endpoint /emit
agent/orchestrator.py    ← plan_task, plan_functions, analyze_errors
agent/generator.py       ← generate_globals, generate_function, patch_code
agent/compiler.py        ← compile_sketch, fix_known_includes, fix_known_api_errors
agent/evaluator.py       ← evaluate, evaluate_visual
agent/grab.py            ← grab_now (webcam via SSH)
agent/remote_uploader.py ← upload PlatformIO + seriale
agent/mi50_server.py     ← server Qwen3.5-9B ROCm
tools/lista.json         ← indice compatto tools (lazy loading)
tools/<nome>.json        ← schemi dettagliati per ogni tool
```
