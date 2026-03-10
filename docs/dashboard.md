# Dashboard real-time — documentazione

Dashboard web SSE (Server-Sent Events) che mostra in tempo reale tutto quello che fa l'agente: token MI50 e M40 in streaming, stato delle funzioni generate, frame webcam, risultati di compilazione e output seriale.

---

## Avvio

Il dashboard parte **automaticamente** quando si lancia `loop.py`. Non serve fare nulla:

```bash
python agent/loop.py "task" --fqbn esp32:esp32:esp32
# → "  📊 Dashboard: http://localhost:7700"
```

Aprire `http://localhost:7700` nel browser per seguire la run in diretta.

Se ci si connette a run già iniziata, il browser riceve tutta la storia (ultimi 500 eventi) e poi si allinea live.

---

## Layout

```
┌─────────────────────────────────────────────────────────┐
│  ● task corrente              [board]  [FASE]  MM:SS    │
├────────────────┬───────────────────┬────────────────────┤
│  MI50          │  M40              │  Webcam            │
│  Qwen3.5-9B    │  Qwen3.5-9B-Q5   │                    │
│  (ROCm)        │  (llama.cpp)      │  [frame 1]         │
│                │                   │  [frame 2]         │
│  💭 thinking   │  ⚙ setup()       │  [frame 3]         │
│  (grigio)      │  ✓ setup()        │                    │
│                │  ⚙ loop()         │  0 frame           │
│  risposta      │  ✓ loop()         │                    │
│  (bianco)      │                   │                    │
│                │  ✅ Compilazione  │                    │
│  ▶ READY       │                   │                    │
│  ▶ VCAP_READY  │                   │                    │
└────────────────┴───────────────────┴────────────────────┘
```

### Colonna MI50
- Thinking (`<think>...</think>`) → grigio corsivo, bordo sinistro
- Risposta → bianco
- Divider di fase → `── PLANNING ──` in viola
- Errori di compilazione → rosso
- Output seriale → giallo ambra
- Log generico → grigio scuro

### Colonna M40
- Badge funzione in corso → `⚙ setup()` (sfondo blu scuro)
- Badge funzione completata → `✓ setup() 14 righe` (sfondo verde scuro)
- Codice generato in streaming → azzurro chiaro

### Colonna Webcam
- 260px larghezza fissa
- Frame inseriti in cima (il più recente è il primo)
- Clic su un frame → lightbox fullscreen
- Contatore frame in alto a destra

---

## Header

| Elemento | Descrizione |
|----------|-------------|
| `●` punto colorato | Verde pulsante = running, Verde fisso = done, Rosso = failed |
| Titolo task | Testo completo del task |
| `[esp32:esp32:esp32]` | FQBN della scheda |
| `[PLANNING]` | Fase corrente |
| `MM:SS` | Tempo trascorso dall'inizio del task |

---

## API per integrazione

Il dashboard espone funzioni Python che i componenti chiamano direttamente. Tutte sono no-op se `dashboard.start()` non è stato chiamato.

### Funzioni di stato

```python
import agent.dashboard as dashboard

# All'avvio di loop.py
dashboard.start()                        # avvia Flask su porta 7700 (daemon thread)
dashboard.task_start("task...", "esp32") # resetta UI, mostra titolo

# Cambio fase
dashboard.phase("planning", "MI50 pianifica il task")
dashboard.phase("generate", "M40 genera funzione per funzione")
dashboard.phase("compile", "tentativo 1/5")
dashboard.phase("upload", "Raspberry Pi")
dashboard.phase("evaluate", "MI50 valuta output")

# Fine run
dashboard.run_end(True, "done")          # dot verde fisso
dashboard.run_end(False, "compile_failed") # dot rosso
```

### Token streaming

```python
# Chiamati automaticamente da mi50_client.py e m40_client.py
dashboard.token("mi50", "<think>")
dashboard.token("mi50", "ragionamento...")
dashboard.token("mi50", "</think>")
dashboard.token("mi50", "risposta JSON...")

dashboard.token("m40", "void setup() {")
dashboard.token("m40", "\n  Serial.begin(115200);")
```

Il frontend JavaScript gestisce i tag `<think>` inline: quando vede `<think>` switcha stile su grigio corsivo, quando vede `</think>` torna bianco.

### Funzioni M40

```python
dashboard.func_start("setup")             # badge ⚙ setup()
dashboard.func_done("setup", righe=14)    # badge ✓ setup() 14 righe
dashboard.notebook_update(
    summary="[GENERATING] task | funzioni=2/4",
    progress="✅ setup()  ✅ readTemp()  ⚙ showTemp()  ⬜ loop()"
)
```

### Compilazione

```python
dashboard.compile_result(
    success=False,
    errors=[{"line": 42, "message": "no member 'clearDisplay'"}],
    attempt=1
)
# Mostra: ❌ Errori compilazione (tentativo 1)
#           riga 42: no member 'clearDisplay'

dashboard.compile_result(success=True, errors=[], attempt=2)
# Mostra: ✅ Compilazione OK (tentativo 2)
```

### Output seriale

```python
dashboard.serial_output(["READY", "VCAP_READY", "Temp: 23.5 C"])
# Ogni riga: ▶ READY
```

### Frame webcam

```python
dashboard.frame("/tmp/grab_local_abc/frame_0.jpg", label="frame 1")
# Carica l'immagine, la converte in base64 e la invia via SSE
# Il frontend la mostra come card con thumbnail cliccabile
```

---

## Protocollo SSE

**Endpoint:** `GET /events`

**Format stream:**
```
data: {"type":"task_start","ts":"14:30:00","task":"...","board":"..."}\n\n
data: {"type":"phase","ts":"14:30:01","name":"planning","detail":"..."}\n\n
data: {"type":"token","ts":"14:30:02","source":"mi50","text":"<think>"}\n\n
data: {"type":"token","ts":"14:30:02","source":"mi50","text":"ragionamento"}\n\n
: keepalive\n\n
```

**Tipi di evento:**

| type | Campi | Descrizione |
|------|-------|-------------|
| `task_start` | `task, board` | Inizio run |
| `phase` | `name, detail` | Cambio fase |
| `token` | `source, text` | Token MI50 o M40 |
| `thinking_start` | `source` | Inizio thinking (alternativo ai tag inline) |
| `thinking_end` | `source` | Fine thinking |
| `func_start` | `nome` | M40 inizia funzione |
| `func_done` | `nome, righe` | M40 finisce funzione |
| `compile_result` | `success, errors[], attempt` | Risultato compilazione |
| `serial_output` | `lines[]` | Output seriale scheda |
| `frame` | `b64, label, path` | Frame webcam in base64 |
| `notebook` | `summary, progress` | Stato notebook |
| `run_end` | `success, reason` | Fine run |
| `log` | `msg, level` | Log generico |

---

## History replay

I nuovi client che si connettono a run già in corso ricevono automaticamente gli ultimi 500 eventi (buffer `_history`). Questo permette di aprire il browser a qualsiasi punto della run e vedere tutto dall'inizio.

---

## Auto-reconnect

Se la connessione SSE cade (server riavviato, rete instabile), il frontend si riconnette automaticamente dopo 3 secondi. Mostra un banner arancione "Connessione persa — riconnessione..." durante il gap.

---

## Dettagli implementazione

**Flask + SSE:**
- Un `queue.Queue(maxsize=200)` per client
- Thread `stream()` fa `q.get(timeout=25)` — keepalive ogni 25 secondi
- Nessuna dipendenza esterna oltre Flask (già nel venv)
- `log.setLevel(logging.ERROR)` — log Werkzeug silenziati in console

**Thread safety:**
- `_clients_lock` protegge la lista dei client
- `_history_lock` protegge il buffer history
- Client disconnessi (queue.Full) vengono rimossi silenziosamente

**Avvio:**
```python
dashboard.start()   # no-op se già avviato (_server_thread.is_alive())
```
Thread daemon — si spegne automaticamente quando termina `loop.py`.

**Porta:** `7700` (costante `PORT` in `dashboard.py`). Modificabile:
```python
dashboard.start(port=8080)
```
