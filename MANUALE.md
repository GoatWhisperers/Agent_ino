# Manuale d'uso — Programmatore di Arduini

Guida pratica per avviare il sistema, assegnare task e seguire il lavoro dei modelli in tempo reale.

---

## 1. Avvio della sessione

Ogni sessione richiede due server attivi: uno per il cervello (MI50) e uno per le mani (M40).
Vanno avviati una volta sola — rimangono in memoria per tutta la sessione.

### Passo 1 — Apri un terminale e attiva il venv

```bash
cd /home/lele/codex-openai/programmatore_di_arduini
source .venv/bin/activate
```

### Passo 2 — Avvia MI50 (cervello, ~10 minuti)

```bash
python agent/mi50_server.py &
```

Il server è pronto quando vedi:

```
[MI50Server] ✅ Modello caricato su cuda. Pronto.
```

Puoi verificarlo in qualsiasi momento:

```bash
curl -s http://localhost:11434/health
# {"status":"ok","model":"qwen3.5-9b","device":"cuda"}
```

### Passo 3 — Avvia M40 (mani, ~30 secondi)

```bash
/mnt/raid0/llama-cpp-m40/start_cuda.sh &
```

Verifica:

```bash
curl -s http://localhost:11435/health
# {"status":"ok"}
```

### Passo 4 — Verifica Raspberry Pi

```bash
ssh lele@192.168.1.167 "echo ok && ls /dev/ttyUSB*"
# ok
# /dev/ttyUSB0
```

Se risponde, l'ESP32 è collegato e pronto.

---

## 2. Assegnare un task

### Forma base

```bash
python agent/loop.py "descrizione del task in italiano"
```

L'agente capisce da solo che si tratta di un ESP32 e usa il Raspberry Pi per il flash.

### Esempi pratici

```bash
# LED che lampeggia
python agent/loop.py "fai lampeggiare un LED sul pin 2 ogni 500ms"

# Sensore di temperatura
python agent/loop.py "leggi la temperatura da un sensore NTC sul pin A0 e stampala sulla seriale ogni secondo"

# Display OLED
python agent/loop.py "mostra 'Ciao mondo' su un display OLED I2C 128x64"

# Comunicazione WiFi
python agent/loop.py "connettiti al WiFi e stampa l'indirizzo IP ottenuto"

# Controllo motore
python agent/loop.py "fai ruotare un servo sul pin 9 da 0 a 180 gradi in loop"
```

### Opzioni utili

```bash
# Solo compilazione — non tocca l'hardware (utile per verificare che il codice compili)
python agent/loop.py "task" --no-upload

# Scheda diversa (default è esp32:esp32:esp32)
python agent/loop.py "task" --fqbn arduino:avr:uno

# Baud rate specifico (default: 115200 per ESP32, 9600 per AVR)
python agent/loop.py "task" --baud 9600

# Continua un progetto già iniziato
python agent/loop.py "aggiungi anche un LED rosso" --mode CONTINUE --project fai_lampeggiare_un_LED

# Modifica un progetto funzionante
python agent/loop.py "cambia la frequenza a 1 secondo" --mode MODIFY --project fai_lampeggiare_un_LED
```

---

## 3. Monitorare il lavoro in tempo reale

### Segui il log in diretta

Ogni run crea un file `logs/run_YYYYMMDD_HHMMSS.jsonl`. Per seguirlo:

```bash
# Ultimo log in formato leggibile
tail -f logs/$(ls -t logs/ | head -1) | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line)
        ev = d.get('event', '?')
        if ev == 'run_start':
            print(f\"\n🚀 AVVIO — task: {d['task']}\")
        elif ev == 'analyst_search':
            print(f\"🔍 ANALYST — {d['n_snippets']} snippet simili nel DB\")
        elif ev == 'orchestrator_plan':
            print(f\"📋 PIANO — {d.get('approach','')[:100]}\")
        elif ev == 'generator_output':
            print(f\"✍️  CODICE generato — {d['code_len']} caratteri\")
        elif ev == 'compile_attempt':
            status = '✅' if d['success'] else '❌'
            print(f\"🔧 COMPILE tentativo {d['attempt']} {status} — {len(d.get('errors',[]))} errori\")
        elif ev == 'error_analysis':
            print(f\"🔬 ANALISI ERRORE — {d.get('analysis','')[:100]}\")
        elif ev == 'remote_upload_result':
            status = '✅' if d['success'] else '❌'
            print(f\"📦 PIO compile {status}\")
        elif ev == 'upload_result':
            status = '✅' if d['success'] else '❌'
            print(f\"⬆️  UPLOAD {status}\")
        elif ev == 'serial_output':
            lines = d.get('lines', [])
            print(f\"📡 SERIALE — {len(lines)} righe ricevute\")
            for l in lines[:5]:
                print(f\"   > {l}\")
        elif ev == 'evaluation':
            status = '✅ SUCCESSO' if d['success'] else '❌ NON RIUSCITO'
            print(f\"🧠 VALUTAZIONE {status} — {d.get('reason','')[:100]}\")
        elif ev == 'run_end':
            status = '🎉 COMPLETATO' if d['success'] else '⚠️  FALLITO'
            print(f\"\n{status}\")
    except:
        pass
" 2>/dev/null
```

Oppure versione semplice (solo eventi, niente parsing):

```bash
tail -f logs/$(ls -t logs/ | head -1)
```

### Cosa aspettarsi — timeline tipica

| Fase | Durata tipica | Cosa sta facendo |
|------|-------------|-----------------|
| Avvio MI50 server | ~10 min | Carica 19 GB di modello su GPU |
| Analyst (Fase 0) | 3-8 min | Cerca codice simile nel DB, analizza |
| Orchestrator (Fase 1) | 3-8 min | Pianifica l'implementazione |
| Generator (Fase 2) | 1-2 min | M40 genera il codice (33 tok/s) |
| Compiler (Fase 3) | 10-30 sec | arduino-cli compila |
| PlatformIO compile | 1-3 min | Prima compilazione, scarica toolchain |
| Upload ESP32 | 20-40 sec | Flash via Raspberry Pi |
| Lettura seriale | 10 sec | Legge output dalla scheda |
| Evaluator (Fase 5) | 3-8 min | MI50 valuta se il task è riuscito |
| Learner (Fase 6) | 3-8 min | MI50 estrae pattern, aggiorna DB |

**Totale tipico: 30-60 minuti per un task nuovo, 15-25 minuti per task simili già nel DB.**

### Stato GPU in tempo reale

```bash
# MI50 (AMD)
watch -n 5 rocm-smi --showmemuse

# M40 (NVIDIA)
watch -n 5 nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu --format=csv
```

### Processi attivi

```bash
ps aux | grep -E "loop.py|mi50_server|llama-server" | grep -v grep
```

---

## 4. Leggere i risultati

### Codice generato

Il codice è in `workspace/current/<nome_progetto>/`:

```bash
# Vedi il codice dell'ultimo progetto
ls workspace/current/
cat workspace/current/<nome_progetto>/*.ino
```

### Progetti riusciti

I task completati con successo vengono copiati in `workspace/completed/`:

```bash
ls workspace/completed/
```

### Log completo di una run

```bash
# Visualizza tutti gli eventi di una run
python3 -c "
import json
for line in open('logs/$(ls -t logs/ | head -1)'):
    d = json.loads(line)
    print(d['ts'][:19], d['event'])
"
```

### Knowledge Base — cosa ha imparato l'agente

```bash
# Ultimi snippet salvati
sqlite3 knowledge/arduino_agent.db \
  "SELECT substr(task_description,1,60), board, created_at FROM snippets ORDER BY created_at DESC LIMIT 10;"

# Storico run (successi e fallimenti)
sqlite3 knowledge/arduino_agent.db \
  "SELECT substr(task,1,50), mode, success, iterations, created_at FROM runs ORDER BY created_at DESC LIMIT 10;"

# Errori appresi
sqlite3 knowledge/arduino_agent.db \
  "SELECT substr(error_pattern,1,60), substr(fix_description,1,60) FROM error_fixes LIMIT 10;"
```

---

## 5. Troubleshooting

### MI50 non risponde / timeout

```bash
# Verifica che il server sia vivo
curl -s http://localhost:11434/health

# Controlla il processo
ps aux | grep mi50_server | grep -v grep

# Se non c'è: riavvia
python agent/mi50_server.py &
```

### M40 non risponde

```bash
curl -s http://localhost:11435/health

# Se non c'è: riavvia
/mnt/raid0/llama-cpp-m40/start_cuda.sh &
```

### Raspberry Pi non raggiungibile

```bash
ping -c 3 192.168.1.167
ssh lele@192.168.1.167 "echo ok"
```

### Porta seriale occupata sul Raspberry

Capita se un test precedente è fallito lasciando `read_serial.py` attivo:

```bash
ssh lele@192.168.1.167 "fuser /dev/ttyUSB0 && pkill -f read_serial; echo liberata"
```

### ESP32 non trovato sul Raspberry

```bash
ssh lele@192.168.1.167 "ls /dev/ttyUSB* 2>/dev/null || echo 'nessun dispositivo USB'"
# Se non c'è: scollega e ricollega il cavo USB dell'ESP32
```

### Compilazione fallisce ripetutamente

L'agente tenta fino a 5 volte con analisi + patch automatica. Se fallisce su tutti i tentativi, guarda il log:

```bash
python3 -c "
import json
for line in open('logs/$(ls -t logs/ | head -1)'):
    d = json.loads(line)
    if d['event'] in ('compile_attempt', 'error_analysis'):
        print(d['event'], '—', str(d)[:200])
"
```

### Task valutato come fallito ma il LED lampeggia

L'Evaluator di MI50 può essere eccessivamente critico. Puoi forzare il successo manuale o assegnare lo stesso task in modalità MODIFY con indicazioni più precise.

---

## 6. Flusso visivo (webcam)

Se il task produce output fisico verificabile (LED, display, movimento), MI50 può usare la webcam sul Raspberry per vedere cosa succede davvero.

Il sistema si attiva automaticamente quando MI50 decide che è utile (`vcap_frames > 0` nel piano).

```
ESP32 → Serial "VCAP_START 6 500" → Raspberry cattura 6 frame ogni 500ms
                                   → Frame inviati al server
                                   → MI50 li guarda e valuta
```

**Nota:** la webcam CSI è montata su `/dev/video0`. Assicurarsi che sia posizionata in modo da vedere il circuito e che ci sia sufficiente illuminazione.

---

## 7. Modalità avanzate

### Batch di task

```bash
# Script per lanciare più task in sequenza
for task in \
  "fai lampeggiare il LED blu ogni 200ms" \
  "fai lampeggiare il LED verde ogni 1000ms" \
  "leggi il pulsante sul pin 4 e accendi il LED"; do
    python agent/loop.py "$task" --fqbn esp32:esp32:esp32
    echo "--- task completato ---"
done
```

### Ispezionare il thinking di MI50

Il ragionamento interno di MI50 (`<think>...</think>`) è sempre salvato nel log:

```bash
python3 -c "
import json
for line in open('logs/$(ls -t logs/ | head -1)'):
    d = json.loads(line)
    t = d.get('thinking', '')
    if t:
        print(f\"=== {d['event']} ===\")
        print(t[:500])
        print()
"
```

### Resettare la Knowledge Base

```bash
# ATTENZIONE: cancella tutto quello che l'agente ha imparato
rm knowledge/arduino_agent.db
rm -rf knowledge/chroma/
python -c "from knowledge.db import init_db; init_db()"
python knowledge/seed_data.py
```

---

## 8. Struttura file di lavoro

```
programmatore_di_arduini/
├── MANUALE.md              ← questo file
├── STATO.md                ← stato corrente del progetto (leggi a inizio sessione)
├── CLAUDE.md               ← istruzioni per Claude Code
│
├── agent/
│   ├── loop.py             ← entry point: python agent/loop.py "task"
│   ├── mi50_server.py      ← server MI50: python agent/mi50_server.py &
│   └── ...                 ← altri moduli (non toccare direttamente)
│
├── workspace/
│   ├── current/            ← progetti in corso (uno per task)
│   └── completed/          ← progetti riusciti (archiviati automaticamente)
│
├── logs/                   ← un file .jsonl per ogni run
│
└── knowledge/
    ├── arduino_agent.db    ← SQLite: snippet, librerie, errori, run
    └── chroma/             ← ChromaDB: ricerca semantica degli snippet
```
