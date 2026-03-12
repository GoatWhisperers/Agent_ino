# STATO — Programmatore di Arduini

> Ultima modifica: 2026-03-12 sera

---

## DOVE SIAMO RIMASTI

### Sessione 2026-03-12

**Risultati della sessione:**
- Tool Agent funzionante end-to-end: task astronave OLED compilato e caricato su ESP32 ✅
- Display OLED mostra l'animazione (astronave + stelle + star warp) ✅
- MI50 ha valutato i frame webcam con evaluate_visual ✅ (torchvision fixato al volo)
- Fix rete: Raspberry Pi raggiungibile via `eth0` (cavo Vodafone) — prima usava porta sbagliata

**Problemi risolti oggi:**
1. `max_new_tokens` troppo basso (512) → troncava il JSON di MI50 → abort
2. MI50 usava chiavi args sbagliate (`function` vs `nome`, `count` vs `n_frames`, `code` diretto)
3. Tool agent subprocess non inviava token streaming alla dashboard (fix HTTP batching)
4. Rete: eth0 è la porta Vodafone (non eno1) — Pi a 192.168.1.167 raggiungibile via eth0

**Stato hardware:**
- MI50 (Docker ROCm): UP, porta 11434
- M40 (llama.cpp): UP, porta 11435
- Raspberry Pi: 192.168.1.167, ESP32 su /dev/ttyUSB0
- Dashboard: porta 7700

---

## TODO PRIORITARI

### [1] Far lavorare MI50 + M40 in team (PRIORITÀ ALTA)
- **Problema**: MI50 genera tutto da solo, M40 non viene usato
- **Fix implementato**: nuovo tool `generate_all_functions` che lancia M40 in parallelo (thread pool)
- **System prompt aggiornato**: istruisce MI50 a usare `generate_all_functions` invece di scrivere codice
- **Da testare**: verificare che MI50 segua il nuovo flusso nella prossima run

### [2] Token streaming dashboard (IMPLEMENTATO, da testare)
- Fix: `_TokenBatcher` in `mi50_client.py` — manda token via HTTP `/emit` ogni 200ms
- Prima: `dashboard.token()` chiamato nel subprocess → ignorato
- Ora: token batched e inviati via HTTP → visibili in dashboard in real-time
- Da verificare che MI50 thinking scorra in dashboard nella prossima run

### [3] Context saturation nel tool agent
- MI50 MAX_INPUT_TOKENS=6144, la conversazione cresce ad ogni step
- Aggiungere conteggio token e troncamento history se messages > 10 step
- Tenere: system + ultimi N scambi + risultati compile/errori

### [4] torchvision nel container MI50 (BUG RICORRENTE)
- Ad ogni restart container: `pip install torchvision==0.20.1 --index-url .../rocm6.2` manuale
- È nel Dockerfile ma non viene installato correttamente all'avvio
- Fix permanente: verificare Dockerfile.mi50 e aggiungere RUN pip install esplicito

### [5] eth0 / rete Vodafone — configurazione permanente
- `eth0` prende IP solo se qualcuno fa `dhcpcd eth0` manualmente dopo boot
- Aggiungere eth0 in `/etc/netplan/50-cloud-init.yaml` con dhcp4: yes
- Così il Pi è raggiungibile automaticamente dopo reboot senza intervento manuale

### [6] Posizionamento webcam
- MI50 ha valutato l'animazione come "paesaggio con edificio" invece di astronave
- La webcam non inquadra bene il display OLED
- Riposizionare fisicamente, usare "📷 Scatta" in dashboard per verificare inquadratura

---

## ARCHITETTURA CORRENTE

### Modelli
- **MI50** (AMD ROCm, Qwen3.5-9B bfloat16): reasoning + planning + valutazione → porta 11434
- **M40** (NVIDIA CUDA, Qwen3.5-9B Q5_K_M): code generation → porta 11435
- `max_new_tokens=8192` ovunque (era 512/1024 — troppo basso)
- Thinking abilitato ovunque

### Tool Agent — flusso ottimale (nuovo)
```
MI50: plan_task
MI50: plan_functions  (descrive funzioni con firma e dettagli)
MI50: generate_globals  (M40 genera #include/#define/variabili)
MI50: generate_all_functions  → thread pool → M40 genera TUTTE in parallelo
MI50: compile → analyze_errors → patch_code → compile
MI50: upload_and_read
MI50: grab_frames  (args: {n_frames:5, interval_ms:1200})
MI50: evaluate_visual
MI50: save_to_kb
MI50: {done: true}
```

### Hardware
- Raspberry Pi 3B: `lele@192.168.1.167` (pwd: pippopippo33$$)
- Accesso: via `eth0` (rete Vodafone, gateway 192.168.1.1)
- ESP32: `/dev/ttyUSB0` sul Raspberry, baud 115200
- OLED SSD1306 128x64: SDA=GPIO21, SCL=GPIO22, addr=0x3C
- Webcam CSI (IMX219): `/dev/video0` sul Raspberry

### Due modalità di run
1. **Tool Agent** (preferito): `python agent/tool_agent.py "task"` o dashboard
2. **Loop classico** (debug): `python agent/loop.py "task"`

### Dashboard (porta 7700)
- Start/Stop taskbar in basso
- Token MI50 in streaming real-time (nuovo fix HTTP batching)
- 📷 Scatta: cattura frame per verifica inquadratura
- Log subprocess: `/tmp/tool_agent.log`

---

## FILE CHIAVE

```
agent/tool_agent.py      ← agente ReAct — genera_all_functions aggiunto
agent/mi50_client.py     ← streaming token via HTTP batching (fix subprocess)
agent/loop.py            ← flusso classico
agent/dashboard.py       ← Flask SSE porta 7700
agent/orchestrator.py    ← plan_task, plan_functions, analyze_errors
agent/generator.py       ← generate_globals, generate_function, patch_code
agent/compiler.py        ← compile_sketch, fix_known_includes, fix_known_api_errors
agent/evaluator.py       ← evaluate, evaluate_visual
agent/grab.py            ← grab_now (webcam via SSH)
agent/remote_uploader.py ← upload PlatformIO + seriale
agent/mi50_server.py     ← server Qwen3.5-9B ROCm
task_astronave.txt       ← prompt task astronave OLED (pronto per dashboard)
tools/lista.json         ← indice tools (lazy loading)
```

---

## COMANDI RAPIDI

```bash
cd /home/lele/codex-openai/programmatore_di_arduini
source .venv/bin/activate

# Avvio server (M40 già up di solito)
bash agent/start_servers.sh

# Avvio dashboard
nohup python3 -c "
import sys; sys.path.insert(0, '.')
import agent.dashboard as d, time
d.start()
while True: time.sleep(60)
" > /tmp/dashboard.log 2>&1 &

# Fix torchvision se evaluate_visual fallisce
docker exec mi50-server pip install torchvision==0.20.1 \
  --index-url https://download.pytorch.org/whl/rocm6.2 -q

# Fix rete Pi (se eth0 non ha IP)
sudo dhcpcd eth0

# Kill processi stuck sul Raspberry
ssh lele@192.168.1.167 "pkill -f esptool; pkill -f 'pio run'"

# Monitor run
tail -f /tmp/tool_agent.log

# Restart MI50
docker stop mi50-server && docker rm mi50-server && bash docker/run_mi50.sh
```
