# PREFLIGHT — Checklist Claude prima di ogni task

> Questo protocollo è eseguito da **Claude** (non dal programmatore/tool_agent).
> Ogni step va eseguito in ordine. Se un check fallisce, fixare prima di andare avanti.

---

## STEP 1 — Inferenza MI50 (ROCm, porta 11434)

Mandare un prompt reale al MI50 e verificare che risponda correttamente.

```bash
curl -s http://localhost:11434/health
```

Se non risponde → avviare con `bash agent/start_servers.sh`.

Test inferenza diretta:

```bash
cd /home/lele/codex-openai/programmatore_di_arduini && source .venv/bin/activate
python -c "
from agent.mi50_client import MI50Client
c = MI50Client()
r = c.chat([{'role':'user','content':'Rispondi solo: OK'}], max_new_tokens=20)
print('MI50:', r)
"
```

**Atteso:** stringa contenente `OK`. Se vuota o errore → investigate log Docker.

```bash
docker logs mi50-server --tail 20
```

---

## STEP 2 — Inferenza M40 (CUDA llama.cpp, porta 11435)

```bash
curl -s http://localhost:11435/health
```

Test inferenza:

```bash
python -c "
import requests, json
r = requests.post('http://localhost:11435/v1/chat/completions', json={
    'model': 'qwen',
    'messages': [{'role':'user','content':'Rispondi solo: OK'}],
    'max_tokens': 20
}, timeout=30)
print('M40:', r.json()['choices'][0]['message']['content'])
"
```

**Atteso:** stringa contenente `OK`. Se timeout → `bash agent/start_servers.sh`.

---

## STEP 3 — Raspberry Pi raggiungibile

```bash
python -c "
import sys; sys.path.insert(0, '.')
from agent.remote_uploader import is_reachable
print('Pi reachable:', is_reachable())
"
```

**Atteso:** `Pi reachable: True`

Se False:
```bash
# Fix rete eth0 (Vodafone)
sudo ip link set eth0 up && sudo dhcpcd eth0
# Poi ri-testa
```

Verificare anche porta seriale e stato processi sul Pi:
```bash
ssh lele@192.168.1.167 "ls /dev/ttyUSB* 2>/dev/null && echo OK || echo NO_DEVICE"
ssh lele@192.168.1.167 "fuser /dev/ttyUSB0 2>/dev/null && echo PORTA_OCCUPATA || echo PORTA_LIBERA"
# Kill processi stuck se necessario:
ssh lele@192.168.1.167 "pkill -f esptool; pkill -f 'pio run'; echo done"
```

---

## STEP 4 — Webcam (grab frame dal Raspberry)

```bash
python -c "
import sys; sys.path.insert(0, '.')
from agent.grab import grab_now
paths = grab_now(n_frames=1)
print('Frame salvato:', paths)
"
```

**Atteso:** lista con un path file `.jpg` esistente. Guardare l'immagine per verificare che la webcam inquadri il display OLED.

Se errore SSH o timeout → verificare che la webcam sia connessa al Pi:
```bash
ssh lele@192.168.1.167 "ls /dev/video* 2>/dev/null || echo NO_WEBCAM"
```

---

## STEP 5 — Memory server (porta 7701)

```bash
curl -s http://127.0.0.1:7701/health | python3 -m json.tool
```

**Atteso:** `{"status":"ok","llm_mode":"disabled",...}`

Se down:
```bash
docker start memoria_ai_server
sleep 3
curl -s http://127.0.0.1:7701/health
```

Se il container non esiste (dopo reboot):
```bash
docker run -d \
  --name memoria_ai_server \
  --restart unless-stopped \
  -p 7701:7701 \
  -v /mnt/raid0/memoria_ai/vault:/vault:rw \
  -v /mnt/raid0/memoria_ai/chroma:/data/chroma:rw \
  -v /mnt/raid0/memoria_ai/runtime:/data/sqlite:rw \
  -v /mnt/raid0/memoria_ai/chroma_cache/chroma:/root/.cache/chroma:rw \
  memoria-ai-server
```

**Nota:** il modello all-MiniLM-L6-v2 è già in `/mnt/raid0/memoria_ai/chroma_cache/` — no download necessario.

---

## STEP 6 — Dashboard funzionante

> La dashboard è visibile da browser su `http://192.168.1.66:7700` (LAN) — la verifica visiva la fa Lele.
> Claude verifica solo che il processo Flask sia attivo e risponda.

```bash
curl -s --max-time 5 http://localhost:7700/ | head -5 || echo "Dashboard DOWN"
```

Se down → avviare:
```bash
nohup python3 -c "
import sys; sys.path.insert(0, '.')
import agent.dashboard as d, time
d.start()
while True: time.sleep(60)
" > /tmp/dashboard.log 2>&1 &
sleep 3
curl -s --max-time 5 http://localhost:7700/ | head -3
```

Screenshot headless non disponibile (no browser/Xvfb). Lele verifica visivamente da browser.

---

## STEP 7 — Warm-up run (Claude esegue, NON il programmatore)

Claude esegue manualmente i passi che userebbe il tool_agent su un **task semplice e diverso**
dal task reale, per verificare che l'intera pipeline funzioni end-to-end.

**Regola:** il warm-up usa un task leggermente diverso dall'esempio che darò al programmatore.
Esempio: se il task reale è "disegna un cerchio", il warm-up è "disegna un quadrato".

### 6a. Genera codice con M40 (generator)

```python
from agent.generator import Generator
gen = Generator()
# Test genera globals
```

### 6b. Compila con arduino-cli (compiler)

```bash
python -c "
import sys; sys.path.insert(0, '.')
from agent.compiler import compile_sketch, check_libraries
libs = check_libraries(['Adafruit_SSD1306', 'Adafruit_GFX_Library', 'Adafruit_BusIO'])
print('Libs:', libs)
"
```

### 6c. Upload e lettura seriale (remote_uploader)

```bash
python -c "
import sys; sys.path.insert(0, '.')
from agent.remote_uploader import check_pio_libraries
ok = check_pio_libraries(['Adafruit SSD1306', 'Adafruit GFX Library'])
print('PIO libs OK:', ok)
"
```

### 6d. Grab frame e valutazione visiva (grab + evaluator)

Già testato in STEP 4. Se grab_now funziona, evaluate_visual funzionerà.

---

## STEP 8 — Calibrazione occhio (calibrate_eye)

Calibra i parametri della webcam per il setup fisico corrente (luce ambiente, distanza display).
Va eseguito **una volta per sessione** o ogni volta che cambia il setup fisico.

```bash
python -c "
import sys; sys.path.insert(0, '.')
from agent.occhio import calibrate_eye
result = calibrate_eye(target='oled')
print('Preset scelto:', result.get('best_preset'))
print('Score:', result.get('scores'))
print('Calibrazione salvata in workspace/eye_calibration.json')
"
```

**Atteso:** preset ottimale identificato (es. `bright`, `standard`, `oled_only`) e file salvato.

Se la calibrazione fallisce (Pi non raggiungibile, webcam assente) → skip e usare preset default.

Il preset salvato viene usato automaticamente da tutti i tool visivi successivi:
`capture_frames`, `detect_motion`, `count_objects`, `describe_scene`.

---

## STEP 9 — Verifica KB (knowledge base)

```bash
sqlite3 knowledge/arduino_agent.db \
  "SELECT task_description, board, created_at FROM snippets ORDER BY created_at DESC LIMIT 5;"
```

Cercare esempi simili al task reale da passare al programmatore:

```bash
python -c "
import sys; sys.path.insert(0, '.')
# Cerca snippet simile al task che voglio dare
from knowledge.query_engine import QueryEngine
qe = QueryEngine()
results = qe.search('OLED SSD1306 display', limit=3)
for r in results:
    print(r.get('task_description'), '|', r.get('board'))
"
```

---

## STEP 10 — Preparare il task per il programmatore

Solo dopo aver superato tutti gli step sopra, Claude prepara il task reale con il contesto completo.

### Template task da dare al programmatore

```
TASK: <descrizione chiara e specifica — più complessa del warm-up>

HARDWARE:
- Board: ESP32 NodeMCU (esp32:esp32:esp32)
- Display: OLED SSD1306 128x64 pixel, monocromatico (solo bianco/nero)
  - Connessione I2C: SDA=GPIO21, SCL=GPIO22, indirizzo 0x3C
  - Costruttore: Adafruit_SSD1306 display(128, 64, &Wire, -1)  ← -1 = no reset pin
  - Init:        display.begin(SSD1306_SWITCHCAPVCC, 0x3C)
  - Colori:      usare SOLO SSD1306_WHITE — mai Adafruit_GFX::WHITE
- LED built-in: GPIO2
- Seriale: 115200 baud

LIBRERIE DISPONIBILI (già installate, NON aggiungere altre):
- Adafruit_SSD1306 2.5.16
- Adafruit_GFX_Library 1.12.5
- Adafruit_BusIO 1.17.4
- Wire.h (built-in ESP32)

INCLUDE CORRETTI:
  #include <Wire.h>
  #include <Adafruit_GFX.h>
  #include <Adafruit_SSD1306.h>

ESEMPIO SIMILE DA KB:
<incollare qui il codice trovato al STEP 7, se disponibile>

STRUMENTI DISPONIBILI (tool_agent):
- plan_task / plan_functions      → MI50 pianifica
- generate_globals                → M40 genera #include, #define, variabili globali
- generate_all_functions          → M40 genera tutte le funzioni in parallelo
- compile                         → arduino-cli locale
- patch_code                      → M40 corregge errori di compilazione
- upload_and_read                 → PlatformIO su Raspberry Pi, legge seriale
- grab_frames                     → webcam CSI cattura frame dell'OLED
- evaluate_visual / evaluate_text → MI50 valuta il risultato
- save_to_kb                      → salva snippet funzionante nel DB

MODELLO SLAVE PER CODICE: M40 (Qwen3.5-9B Q5_K_M GGUF, porta 11435)
- M40 genera TUTTO il codice (globals + funzioni)
- MI50 NON scrive mai codice, solo ragiona e coordina

NOTA IMPORTANTE: il display è monocromatico, non ha colori.
Coordinate: origine (0,0) in alto a sinistra. Max 128x64 pixel.
```

---

## Semaforo pre-launch

| Check | Comando verifica | Atteso |
|-------|-----------------|--------|
| MI50 health | `curl http://localhost:11434/health` | `{"status":"ok"}` |
| M40 health | `curl http://localhost:11435/health` | risposta HTTP 200 |
| MI50 inferenza | test chat → OK | stringa "OK" |
| M40 inferenza | test chat → OK | stringa "OK" |
| Raspberry Pi | `is_reachable()` | `True` |
| Porta seriale | SSH → `ls /dev/ttyUSB0` | device presente |
| Porta libera | SSH → `fuser /dev/ttyUSB0` | PORTA_LIBERA |
| Webcam | `grab_now(n_frames=1)` | path .jpg valido |
| Dashboard | `curl http://localhost:7700/health` | ok |
| Librerie locali | `check_libraries(...)` | tutte presenti |
| Librerie Pi | `check_pio_libraries(...)` | tutte presenti |
| Memory server | `curl http://127.0.0.1:7701/health` | `{"status":"ok"}` |
| Calibrazione occhio | `calibrate()` | preset salvato in eye_calibration.json |
| KB esempio | `qe.search(task)` | snippet simile (se esiste) |

**Solo se tutti i check sono verdi → lanciare il programmatore.**

```bash
python agent/tool_agent.py "<task>" --fqbn esp32:esp32:esp32
```

---

## Note operative

- Se MI50 container va riavviato (fix `eos_token_id`):
  ```bash
  docker stop mi50-server && docker rm mi50-server && bash docker/run_mi50.sh
  # Se evaluate_visual fallisce (torchvision):
  docker exec mi50-server pip install torchvision==0.20.1 \
    --index-url https://download.pytorch.org/whl/rocm6.2 -q
  ```
- Il warm-up (STEP 6) può essere saltato se l'ultima run è avvenuta nella stessa sessione e tutti i check sono verdi.
- Se il Pi non è raggiungibile via eth0: `sudo ip link set eth0 up && sudo dhcpcd eth0`
