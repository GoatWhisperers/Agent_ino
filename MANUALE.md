# Manuale del Progetto — Programmatore di Arduini

> Versione 1.0 — 2026-03-19
> Autori: Lele + Claude

---

## Indice

1. [Cos'è questo progetto](#1-cosè-questo-progetto)
2. [Filosofia di design](#2-filosofia-di-design)
3. [Architettura hardware](#3-architettura-hardware)
4. [Architettura software](#4-architettura-software)
5. [I modelli AI e i loro ruoli](#5-i-modelli-ai-e-i-loro-ruoli)
6. [Il flusso completo — passo per passo](#6-il-flusso-completo--passo-per-passo)
7. [Il context management MemGPT-style](#7-il-context-management-memgpt-style)
8. [La Knowledge Base](#8-la-knowledge-base)
9. [Il sistema di valutazione](#9-il-sistema-di-valutazione)
10. [La Dashboard](#10-la-dashboard)
11. [Il protocollo PREFLIGHT](#11-il-protocollo-preflight)
12. [Perché non un singolo prompt?](#12-perché-non-un-singolo-prompt)
13. [Bug noti e workaround](#13-bug-noti-e-workaround)
14. [Roadmap futura](#14-roadmap-futura)

---

## 1. Cos'è questo progetto

Il **Programmatore di Arduini** è un agente AI autonomo che prende in input una descrizione
in linguaggio naturale ("fai lampeggiare il LED ogni 500ms", "mostra una pallina che rimbalza
sul display OLED") e, senza intervento umano:

1. **Pianifica** la soluzione (struttura del codice, funzioni necessarie, librerie)
2. **Genera** il codice Arduino/ESP32 in C++
3. **Compila** il codice localmente con arduino-cli
4. **Carica** il firmware sull'hardware fisico via Raspberry Pi
5. **Osserva** il risultato (output seriale + frame webcam)
6. **Valuta** se il task è stato completato correttamente
7. **Impara** salvando il codice funzionante nella knowledge base

Il sistema è progettato per hardware fisico reale, non simulazioni. Ogni run termina con
codice che gira su un ESP32 reale, con un display OLED reale, inquadrato da una webcam reale.

---

## 2. Filosofia di design

### 2.1 Due modelli, due ruoli distinti

Il principio fondamentale è la **separazione netta tra ragionamento e generazione di codice**:

- **MI50 ragiona.** Non scrive mai codice. Pianifica, analizza errori, valuta risultati.
- **M40 genera.** Non ragiona. Scrive codice velocemente dato un contesto preciso.

Questa separazione non è ovvia — un unico modello potrebbe fare entrambe le cose.
La scelta nasce da caratteristiche opposte dei due compiti:

| Caratteristica     | Ragionamento (MI50)         | Generazione codice (M40)     |
|--------------------|-----------------------------|------------------------------|
| Velocità richiesta | Lenta va bene               | Deve essere rapida           |
| Precisione         | Alta (il piano deve reggere)| Media (il compilatore corregge)|
| Parallelismo       | Un passo alla volta         | Tutte le funzioni in parallelo|
| VRAM necessaria    | Molta (bfloat16 completo)   | Meno (quantizzato Q5_K_M)    |

### 2.2 Il loop chiuso è tutto

La differenza fondamentale rispetto a "chiedere il codice a ChatGPT" è il **loop chiuso**:

```
Genera → Compila → [errori?] → Patcha → Compila → Carica → Osserva → Valuta → Impara
```

Un modello che genera codice senza feedback non sa se funziona. Questo sistema lo sa.
Sa se il compilatore si lamenta, sa se l'ESP32 crasha al boot, sa se il display mostra
quello che deve mostrare. E reagisce di conseguenza, autonomamente.

### 2.3 La KB come memoria a lungo termine

Ogni run di successo produce un esempio che viene salvato nel database. Le run successive
partono da esempi funzionanti — include corretti, costruttori corretti, API testate su
hardware reale. Il sistema migliora con l'uso.

---

## 3. Architettura hardware

```
┌─────────────────────────────────────────────────────┐
│  SERVER (192.168.1.66)                              │
│                                                     │
│  ┌──────────────┐      ┌──────────────────────┐     │
│  │ MI50 (AMD)   │      │ M40 (NVIDIA)         │     │
│  │ ROCm Docker  │      │ llama.cpp nativo      │     │
│  │ Qwen3.5-9B   │      │ Qwen3.5-9B Q5_K_M    │     │
│  │ bfloat16     │      │ GGUF quantizzato      │     │
│  │ 32GB VRAM    │      │ 11.5GB VRAM           │     │
│  │ porta 11434  │      │ porta 11435           │     │
│  └──────────────┘      └──────────────────────┘     │
│                                                     │
│  ┌───────────────────────────────────────────┐      │
│  │ Tool Agent (Python)                       │      │
│  │ + arduino-cli  (compilazione locale)      │      │
│  │ + Dashboard Flask (porta 7700)            │      │
│  └───────────────────────────────────────────┘      │
└────────────────────────┬────────────────────────────┘
                         │ SSH / SCP (sshpass)
                         │ 192.168.1.167
┌────────────────────────▼────────────────────────────┐
│  RASPBERRY PI 3B                                    │
│                                                     │
│  PlatformIO (compile + upload)                      │
│  read_serial.py   (lettura UART)                    │
│  libcamera / v4l2 (cattura webcam CSI)              │
│                                                     │
│   /dev/ttyUSB0 (CP2102)      /dev/video0            │
│         │                         │                 │
└─────────┼─────────────────────────┼─────────────────┘
          │                         │
   ┌──────▼──────┐           ┌──────▼──────┐
   │  ESP32      │           │ Webcam CSI  │
   │  NodeMCU    │◄──────────│ IMX219      │
   │             │  inquadra │ (guarda     │
   │  OLED SSD1306│          │  il display)│
   │  128x64 I2C │           └─────────────┘
   └─────────────┘
```

### Hardware specifico

| Componente        | Dettaglio                                              |
|-------------------|--------------------------------------------------------|
| ESP32             | NodeMCU, FQBN `esp32:esp32:esp32`                     |
| OLED              | SSD1306 128x64, I2C addr=0x3C, SDA=GPIO21, SCL=GPIO22 |
| Connettore serial | CP2102 USB-UART, `/dev/ttyUSB0`, baud 115200           |
| Webcam            | IMX219 CSI, `/dev/video0`                             |
| Raspberry Pi      | Pi 3B, Raspberry Pi OS, eth0 su rete 192.168.1.1/24   |

### Librerie Arduino installate

Disponibili sia su arduino-cli locale che su PlatformIO sul Raspberry Pi:

- `Adafruit SSD1306` 2.5.16
- `Adafruit GFX Library` 1.12.5
- `Adafruit BusIO` 1.17.4
- Tutte le librerie built-in del framework ESP32 (Wire, WiFi, EEPROM, ecc.)

---

## 4. Architettura software

```
programmatore_di_arduini/
│
├── agent/
│   ├── tool_agent.py       ← CUORE: agente ReAct, loop MI50 + dispatch tools
│   ├── mi50_client.py      ← Client HTTP per MI50, streaming token, TokenBatcher
│   ├── mi50_server.py      ← Server Flask nel container ROCm (Qwen3.5 bfloat16)
│   ├── m40_client.py       ← Client HTTP per M40 (llama.cpp OpenAI-compat)
│   ├── orchestrator.py     ← MI50: plan_task, plan_functions, analyze_errors
│   ├── generator.py        ← M40: generate_globals, generate_function, patch_code
│   ├── compiler.py         ← arduino-cli locale, fix_known_includes, fix_known_api_errors
│   ├── remote_uploader.py  ← SSH/SCP Raspberry, PlatformIO upload, lettura seriale
│   ├── evaluator.py        ← MI50: evaluate_text, evaluate_visual (frame webcam)
│   ├── grab.py             ← Cattura frame webcam dal Raspberry via SSH
│   ├── notebook.py         ← Taccuino operativo: traccia piano, assembla .ino finale
│   ├── dashboard.py        ← Flask SSE porta 7700, frame persistenti su disco
│   ├── learner.py          ← Salva snippet funzionanti nella KB
│   └── start_servers.sh    ← Avvia MI50 (Docker ROCm) + M40 (llama-server)
│
├── knowledge/
│   ├── arduino_agent.db    ← SQLite: snippet funzionanti per board+task
│   └── query_engine.py     ← Ricerca snippet per task (text search + semantic)
│
├── docker/
│   ├── Dockerfile.mi50     ← ROCm + HuggingFace Transformers + torchvision
│   └── run_mi50.sh         ← Avvio container con mount agent/mi50_server.py
│
├── tools/
│   ├── lista.json          ← Indice tool disponibili (sempre in context a MI50)
│   └── <nome>.json         ← Guide lazy-load per ogni tool
│
├── workspace/
│   └── .frames_cache.json  ← Cache frame webcam (max 20, persiste tra sessioni)
│
├── CLAUDE.md               ← Istruzioni operative per Claude (AI assistant)
├── PREFLIGHT.md            ← Checklist pre-lancio (eseguita da Claude)
├── STATO.md                ← Stato corrente del progetto (aggiornato a fine sessione)
└── MANUALE.md              ← Questo file
```

---

## 5. I modelli AI e i loro ruoli

### MI50 — Il "cervello" (reasoning)

- **GPU**: AMD Radeon MI50 (32GB HBM2)
- **Framework**: ROCm + HuggingFace Transformers, dentro container Docker
- **Modello**: Qwen3.5-9B in bfloat16 (precisione piena, non quantizzato)
- **Porta**: 11434
- **Thinking**: abilitato — il modello usa `<think>...</think>` per ragionare prima di rispondere
- **Velocità**: lenta (20-30 minuti per chiamata complessa con thinking abilitato)
- **Compiti**:
  - `plan_task` — interpreta il task, decide l'approccio, le librerie, se usare la webcam
  - `plan_functions` — divide il programma in funzioni, descrive firma e compito di ognuna
  - `analyze_errors` — analizza errori di compilazione persistenti (usato raramente)
  - `evaluate_text` — valuta output seriale, decide se il task è completato
  - `evaluate_visual` — analizza frame webcam (vision-language), vede il display fisico

**Regola fondamentale**: MI50 NON scrive mai codice. Se genera codice negli args
invece di chiamare i tool, il sistema lo ignora (`_truncate_to_first_action`).

### M40 — Il "programmatore" (code generation)

- **GPU**: NVIDIA Tesla M40 (11.5GB GDDR5)
- **Framework**: llama.cpp nativo (CUDA), endpoint OpenAI-compatibile
- **Modello**: Qwen3.5-9B Q5_K_M GGUF (quantizzato ~5 bit per peso)
- **Porta**: 11435
- **Thinking**: disabilitato — risponde direttamente senza catena di ragionamento
- **Velocità**: rapida (5-15 secondi per funzione)
- **Compiti**:
  - `generate_globals` — scrive `#include`, `#define`, oggetti globali
  - `generate_function` — scrive UNA funzione completa (chiamato in parallelo per tutte)
  - `patch_code` — corregge il codice dato gli errori del compilatore

**Parallelismo**: tutte le funzioni vengono generate contemporaneamente con
`ThreadPoolExecutor`. Se il piano prevede `setup`, `loop`, `updateBall`, `drawFrame`
→ M40 le genera tutte e 4 in parallelo, poi il Notebook le assembla nel `.ino` finale.

---

## 6. Il flusso completo — passo per passo

```
INPUT: "Animazione pallina rimbalzante su OLED SSD1306"
FQBN:  esp32:esp32:esp32
```

### Fase 0 — Inizializzazione

```
tool_agent.py avvia _Session(task, fqbn)
_ContextManager inizializza: system prompt + anchor vuoto
```

### Fase 1 — plan_task (MI50)

MI50 legge il task e produce un piano strutturato:
```json
{
  "approach": "Animazione con millis(), posizione float, rimbalzo sui 4 bordi",
  "libraries_needed": ["Adafruit_SSD1306", "Adafruit_GFX", "Wire"],
  "key_points": ["usa fillCircle", "clearDisplay ogni frame", "nessun delay()"],
  "vcap_frames": 3
}
```

### Fase 2 — plan_functions (MI50)

MI50 divide il programma in funzioni con firma e compito precisi:
```json
{
  "globals_hint": "Adafruit_SSD1306 display(128,64,&Wire,-1); float bx,by,vx,vy; int bounces;",
  "funzioni": [
    {"nome": "setup",      "firma": "void setup()",      "compito": "init Serial, Wire, display"},
    {"nome": "loop",       "firma": "void loop()",       "compito": "aggiorna ogni 30ms con millis()"},
    {"nome": "updateBall", "firma": "void updateBall()", "compito": "muove e gestisce rimbalzi"},
    {"nome": "drawFrame",  "firma": "void drawFrame()",  "compito": "clearDisplay + fillCircle + display()"}
  ]
}
```

Il Notebook viene inizializzato con questo piano.

### Fase 3 — KB search automatico

**Prima di generate_globals**, il tool_agent cerca nella KB un esempio simile:
```
search("Animazione OLED SSD1306 rimbalzo display")
→ trova template SSD1306 funzionante (testato su hardware reale)
→ sess.kb_example = "<codice con include corretti, costruttore corretto, SSD1306_WHITE>"
```
Questo esempio viene passato a M40 come riferimento.

### Fase 4 — generate_globals (M40)

M40 riceve il `globals_hint` dal notebook + l'esempio KB.
In 5-10 secondi genera:
```cpp
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_W 128
#define SCREEN_H 64
#define OLED_ADDR 0x3C

Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);
float bx = 64, by = 32, vx = 2.5, vy = 1.8;
int bounces = 0;
unsigned long lastFrame = 0;
```

### Fase 5 — generate_all_functions (M40, parallelo)

Tutti i thread partono simultaneamente:
```
Thread 1: M40 → setup()       [10s]
Thread 2: M40 → loop()        [8s]
Thread 3: M40 → updateBall()  [12s]  ← il più lento
Thread 4: M40 → drawFrame()   [7s]
─────────────────────────────────────
Tempo totale: ~12s (tempo del più lento)
invece di:   37s se in sequenza
```

Il Notebook assembla tutto in un unico file `.ino`.

### Fase 6 — compile (arduino-cli locale)

```
arduino-cli compile --fqbn esp32:esp32:esp32 /tmp/tool_agent_XXXXX/
```

**Se errori** → `fix_known_api_errors()` corregge errori noti automaticamente
→ `patch_code` (M40 riscrive le parti errate) → `compile` di nuovo.
Massimo 3 cicli di patch/compile.

### Fase 7 — upload_and_read (Raspberry Pi)

```
1. Kill processi stuck: pkill esptool, pkill pio
2. SCP del codice → ~/projects/agente_<task>/src/main.cpp
3. PlatformIO compile sul Pi (verifica finale con toolchain nativa)
4. esptool flasha il firmware su /dev/ttyUSB0
5. Attende 3s boot ESP32
6. read_serial.py legge la seriale per N secondi
```

Output seriale catturato: `"BOUNCE 1\nBOUNCE 2\nBOUNCE 3\n..."`

### Fase 8 — grab_frames + evaluate_visual (se task usa display)

```
grab_now(n_frames=3)
→ SSH → libcamera/v4l2 → 3 JPEG salvati localmente
→ MI50 vision-language analizza le immagini:
  "Vedo una pallina bianca che si muove sul display OLED. success: true"
```

Se il task non usa display → `evaluate_text` valuta solo l'output seriale.

### Fase 9 — save_to_kb

Il codice funzionante viene salvato nel database con task, board, librerie e tag.

### Fase 10 — done

```json
{"done": true, "success": true, "reason": "Pallina rimbalzante visibile sul display"}
```

---

## 7. Il context management MemGPT-style

MI50 ha una context window limitata (~6144 token). Il tool_agent la gestisce
con un sistema a tre livelli ispirato a MemGPT:

```
┌──────────────────────────────────────────────────────┐
│ [SYSTEM]  ~150 token — fisso                         │
│ Regole, formato tool call, flusso atteso, hw info    │
├──────────────────────────────────────────────────────┤
│ [ANCHOR]  ~300-800 token — ricostruito ogni step     │
│  · Task corrente + FQBN                              │
│  · Step già completati (compressi: "✓ plan_task: …") │
│  · Codice attuale (troncato se >35 righe)            │
│  · Ultimi 3 errori di compilazione                   │
├──────────────────────────────────────────────────────┤
│ [SLIDING WINDOW]  5 turni (10 messaggi)              │
│  I turni più vecchi vengono compressi nell'anchor    │
│  I turni recenti rimangono completi                  │
└──────────────────────────────────────────────────────┘
```

**Vantaggio**: MI50 vede sempre lo stato corrente preciso senza accumulare
token inutili. La finestra non cresce all'infinito — i vecchi turni vengono
riassunti e inseriti nell'anchor.

---

## 8. La Knowledge Base

Database SQLite in `knowledge/arduino_agent.db`, tabella `snippets`.

### Schema

| Campo          | Tipo    | Descrizione                                          |
|----------------|---------|------------------------------------------------------|
| id             | TEXT    | UUID univoco                                         |
| task_description | TEXT  | Descrizione del task in linguaggio naturale          |
| board          | TEXT    | FQBN (es. `esp32:esp32:esp32`)                       |
| code           | TEXT    | Codice Arduino funzionante e testato su hardware     |
| libraries      | TEXT    | JSON array librerie usate                            |
| tags           | TEXT    | JSON array tag per ricerca                           |
| run_count      | INTEGER | Quante volte questo snippet è stato usato            |
| success_count  | INTEGER | Quante volte ha portato a successo                   |
| created_at     | TEXT    | Data creazione                                       |

### Come viene usata

**Durante la generazione**: prima di `generate_globals`, il tool_agent cerca
automaticamente uno snippet con lo stesso board e task simile. Il codice trovato
viene passato a M40 come "esempio funzionante dalla KB" — M40 lo usa per
assicurarsi di usare gli include, i costruttori e le API corretti.

**Perché è importante**: le API di Adafruit_SSD1306, ad esempio, hanno
particolarità (costruttore a 4 parametri, colori monocromatici, getTextBounds
a 7 argomenti) che i modelli spesso sbagliano perché nei training data ci sono
versioni diverse. Un esempio testato su hardware reale è più affidabile di
qualsiasi prompt.

**Valore nel tempo**: più il sistema viene usato, più la KB si riempie di codice
verificato fisicamente. Le run future beneficiano di tutti gli esempi precedenti.
È la "memoria a lungo termine" del programmatore.

---

## 9. Il sistema di valutazione

### evaluate_text

MI50 riceve il task originale + l'output seriale e decide:
- `success: true/false`
- `reason`: spiegazione in linguaggio naturale
- `suggestions`: suggerimenti per migliorare se fallisce

### evaluate_visual

MI50 è un modello vision-language (Qwen3.5-VL). Riceve:
- Task originale in linguaggio naturale
- N frame JPEG dalla webcam (il display OLED fisico inquadrato)
- Output seriale (contesto aggiuntivo)

Produce la stessa struttura di evaluate_text, ma "vedendo" effettivamente
cosa appare sull'hardware reale. Non simula — guarda davvero.

### Quando si usa quale

- Task con display OLED/LCD → `grab_frames` + `evaluate_visual`
- Task con LED, seriale, WiFi, sensori → solo `evaluate_text`

La decisione viene presa da MI50 durante `plan_task` (campo `vcap_frames`).
Se `vcap_frames > 0` → il task richiede verifica visiva.

---

## 10. La Dashboard

Interfaccia web real-time su porta 7700, visibile dalla rete locale su
`http://192.168.1.66:7700`.

**Tecnologia**: Flask con Server-Sent Events (SSE). Nessun WebSocket,
funziona su qualsiasi browser senza librerie client speciali.

**Cosa mostra in tempo reale**:
- Token MI50 in streaming (vedi il modello "pensare" mentre pianifica)
- Token M40 in streaming per ogni funzione generata
- Fase corrente (PLAN → GLOBALS → GEN PARALLELO → COMPILE → UPLOAD → EVAL)
- Errori di compilazione (con numero di riga e messaggio)
- Output seriale dell'ESP32 (aggiornato live)
- Frame webcam dell'OLED (le immagini scattate durante evaluate_visual)
- Risultato finale (success/fail + reason da MI50)

**Frame persistenti**: salvati in `workspace/.frames_cache.json` (max 20).
Al riavvio della dashboard i frame precedenti vengono ricaricati automaticamente.

**Token batching**: i token MI50 vengono inviati alla dashboard ogni 200ms
(non uno per uno) tramite `_TokenBatcher` in mi50_client.py.

**Avvio stabile**:
```bash
nohup python3 -c "
import sys; sys.path.insert(0, '.')
import agent.dashboard as d, time
d.start()
while True: time.sleep(60)
" > /tmp/dashboard.log 2>&1 &
```
Va avviata come processo indipendente — non sopravvive alla morte del tool_agent
se avviata come thread interno.

---

## 11. Il protocollo PREFLIGHT

Prima di lanciare qualsiasi task, Claude esegue una sequenza di verifiche
definita in `PREFLIGHT.md`. Obiettivo: garantire che tutta la pipeline funzioni
prima di affidarsi al programmatore automatico.

### I check

| Step | Cosa verifica | Metodo |
|------|--------------|--------|
| 1 | MI50 risponde con inferenza reale | `MI50Client().generate(...)` → "OK" |
| 2 | M40 risponde con inferenza reale | POST `/v1/chat/completions` → "OK" |
| 3 | Raspberry Pi raggiungibile | `is_reachable()` → True |
| 4 | Porta seriale libera | SSH → `fuser /dev/ttyUSB0` → free |
| 5 | Webcam funzionante | `grab_now(n_frames=1)` → JPEG valido |
| 6 | Dashboard attiva | `curl http://localhost:7700/` |
| 7 | Librerie locali OK | `check_libraries(["Adafruit_SSD1306", ...])` |
| 8 | Librerie PIO sul Pi OK | `check_pio_libraries(...)` |
| 9 | Warm-up compile | Compila sketch noto → zero errori |
| 10 | Warm-up upload + grab | Upload su ESP32, grab frame, verifica visiva |
| 11 | KB search | Cerca esempio simile al task reale |

### Il warm-up run

Un task semplice (diverso dal task reale che verrà assegnato) viene eseguito
da Claude manualmente, passo per passo, usando gli stessi tool del programmatore.
Esempio: se il task reale è "cerchio animato", il warm-up è "quadrato statico".

Se tutto il warm-up funziona → **semaforo verde** → si lancia il task vero.

### Perché è necessario

Il programmatore ha molti punti di fallimento:
- MI50 o M40 con OOM, crash, o stuck dopo una run precedente
- Raspberry Pi non raggiungibile (rete, reboot, eth0 non configurato)
- Porta seriale occupata da esptool stuck nella run precedente
- Webcam non funziona (processo video zombie, CSI disconnesso)
- Librerie mancanti su arduino-cli o PlatformIO

Il PREFLIGHT scopre tutti questi problemi prima, quando è facile correggerli.

---

## 12. Perché non un singolo prompt?

Domanda legittima: perché tutta questa complessità invece di mandare il task
direttamente al modello e prendere il codice?

### Quando un singolo prompt funzionerebbe

Per task semplici e standard, un prompt diretto a M40 con le istruzioni corrette
funziona nell'80-90% dei casi:

```
Task che funzionerebbero con prompt singolo:
- "Fai lampeggiare il LED su GPIO2 ogni 500ms"
- "Scrivi Hello World su display OLED SSD1306"
- "Leggi temperatura da DHT22 e stampala sulla seriale"
```

In questi casi, il tool agent è sovradimensionato. Un prompt di 30 secondi
darebbe lo stesso risultato di una run da 30-60 minuti.

### Quando il singolo prompt fallisce

**Task complessi** (>150 righe, più componenti interagenti): il modello
tende a perdere il filo logico. La divisione in funzioni con firma e compito
precisi risolve questo — M40 scrive una funzione alla volta, non l'intero sistema.

**Errori di compilazione**: il modello non sa se il codice compila. Produce
spesso include sbagliati, API inesistenti, tipi errati. Il loop automatico
compile→patch corregge questi errori senza intervento umano.

**Verifica fisica**: nessun modello sa se l'ESP32 crasha al boot, se il display
mostra quello giusto, se i sensori rispondono. La webcam + evaluate_visual è
l'unico modo per verificare il risultato reale senza un umano davanti all'hardware.

**Deriva delle librerie**: le API di Adafruit_SSD1306 hanno particolarità che i
modelli spesso sbagliano (costruttore a 4 parametri, solo SSD1306_WHITE,
getTextBounds a 7 argomenti). La KB con esempi testati su questo hardware specifico
corregge questi errori sistematicamente.

### Il vero valore: il loop chiuso

```
Prompt singolo:   Genera → [non sai se funziona]

Questo sistema:   Genera → Compila → [errori?] → Patcha
                  → Carica → Osserva → Valuta → Impara
```

Il valore non è nella generazione di codice — M40 da solo è già bravo.
Il valore è nel **feedback loop automatico su hardware fisico reale**, senza
nessun intervento umano tra "dai il task" e "guarda il risultato".

### Il trade-off onesto

|                   | Prompt singolo      | Tool Agent                    |
|-------------------|---------------------|-------------------------------|
| Task semplice     | 30 secondi          | 30-60 minuti                  |
| Task complesso    | Spesso fallisce     | Alta probabilità di successo  |
| Errori libreria   | Non li vede         | Li corregge automaticamente   |
| Verifica fisica   | Manuale (tu guardi) | Automatica (webcam + AI)      |
| Apprendimento     | Nessuno             | KB si arricchisce ogni run    |
| Intervento umano  | Necessario          | Zero                          |

**Conclusione**: il sistema ha un overhead significativo per task semplici.
Il suo valore emerge su task complessi, quando si vuole autonomia completa,
e quando si costruisce una libreria di codice testato che migliora nel tempo.

---

## 13. Bug noti e workaround

### MI50 genera testo libero invece di JSON tool call

**Causa**: il modello continua a generare dopo il JSON, simulando risultati finti
di tool call che non sono stati eseguiti ("run-ahead hallucination").
**Fix attivo**: `_truncate_to_first_action()` in tool_agent.py — tronca la risposta
al primo JSON valido, ignora tutto il resto.
**Fix EOS**: `eos_token_id=[248044, 248046]` in mi50_server.py — ferma la generazione
al token di fine turno. Richiede restart del container Docker per attivarsi.

### M40 usa include sbagliati

**Causa**: nei dati di training ci sono versioni diverse delle librerie Adafruit.
**Fix 1**: `fix_known_includes()` in compiler.py — correzione automatica prima di compilare.
**Fix 2**: `SYSTEM_GLOBALS` ha regole esplicite sugli include corretti.
**Fix 3**: KB example passato a M40 — esempi testati su questo hardware specifico.

### Costruttore Adafruit_SSD1306 sbagliato

**Causa**: M40 usa il 4° parametro come indirizzo I2C invece che come reset pin.
**Fix**: regola esplicita in SYSTEM_GLOBALS e SYSTEM_PATCH:
```cpp
// CORRETTO: 4° parametro è rst_pin, NON I2C addr. Usa sempre -1.
Adafruit_SSD1306 display(128, 64, &Wire, -1);
// L'indirizzo I2C (0x3C) va in begin():
display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
```

### Porta seriale occupata dal processo precedente

**Causa**: esptool o PlatformIO rimasto stuck sul Raspberry dalla run precedente.
**Fix**: `pkill -f esptool; pkill -f 'pio run'` eseguito automaticamente prima di ogni upload
in `_phase_upload_serial_remote()` in loop.py e `upload_and_read_remote()` in remote_uploader.py.

### upload_pio timeout (120s)

**Causa**: PlatformIO sul Pi deve compilare il codice anche lato Raspberry (oltre alla
compilazione locale arduino-cli), più il flash dell'ESP32.
**Fix**: timeout portato a 160s. Il flash tipicamente richiede 35-40s.

### OOM su MI50

**Causa**: VRAM non liberata tra richieste consecutive.
**Fix**: `torch.cuda.empty_cache()` dopo ogni `model.generate()` nei 3 endpoint
di mi50_server.py. Gestito anche da `_processor_lock` per thread safety.

### torchvision scompare dopo restart container MI50

**Causa**: immagine Docker costruita prima che torchvision fosse aggiunto al Dockerfile.
**Fix permanente**: rebuild con `--no-cache` (fatto 2026-03-19):
```bash
docker stop mi50-server && docker rm mi50-server
docker build --no-cache -f docker/Dockerfile.mi50 -t mi50-server .
bash docker/run_mi50.sh
```
**Verifica**: `docker exec mi50-server python3 -c "import torchvision; print(torchvision.__version__)"`

---

### MI50 entra in loop di thinking su dettagli irrilevanti

**Causa**: thinking abilitato su `plan_task` porta MI50 a ragionare per ore su
dettagli già noti (es. nome esatto della libreria quando è specificato nel task).
**Osservazione**: il context non era troncato (max 2120/6144 token) — il problema
era il thinking stesso che generava dubbi dove non ce n'erano.
**Fix operativo**: se MI50 si blocca su plan_task > 30 minuti, interrompere e
ricostruire manualmente il checkpoint con il risultato di plan_task (già presente
nel reasoning del log), poi riprendere da step 2 con `--resume`.
**Fix nel prompt** (aggiunto a `_PLAN_SYSTEM`): indicare esplicitamente che le librerie
nel task sono già corrette e non richiedono verifica.
**Nota**: il thinking rimane abilitato — è necessario per ragionare su fisica,
algoritmi, struttura del codice. Solo i dettagli già esplicitamente forniti
nel task non richiedono ragionamento aggiuntivo.

---

### Truncation del contesto MI50 (potenziale, non ancora osservata)

**Limite**: `MAX_INPUT_TOKENS = 6144` in mi50_server.py. Troncamento dalla destra
(fine del prompt). Il warning appare nel log Docker: `⚠️ Input troncato a 6144 token`.
**Rischio**: nei task futuri con context window molto piena (molti turni +
codice lungo + errori), informazioni importanti in fondo al prompt potrebbero
essere tagliate.
**Monitoraggio**: controllare `docker logs mi50-server | grep troncato` dopo ogni run.
**Fix se necessario**: aumentare `MAX_INPUT_TOKENS` (attualmente 6144, la GPU ha
32GB VRAM con ~12GB liberi) oppure ridurre il context anchor.

---

## 14. Roadmap futura

### A breve

- [ ] **Dockerfile.mi50 con torchvision stabile** — eliminare il reinstall manuale
- [ ] **Dashboard come servizio persistente** — sopravvive ai restart del tool_agent
- [ ] **Test di regressione** — suite di task standard con risultato atteso verificabile
- [ ] **Compilazione-only mode** — verifica senza upload, per sviluppo rapido

### A medio termine

- [ ] **Multi-board**: supporto Arduino Uno (`arduino:avr:uno`) oltre a ESP32
- [ ] **WiFi tasks**: ESP32 che pubblica dati su server locale (MQTT, HTTP POST)
- [ ] **Multi-componente**: task con sensori + display + LED + logica
- [ ] **Retry intelligente**: se evaluate suggerisce "testo troppo piccolo",
      MI50 modifica il codice specificamente per quel problema senza ripartire da zero

### Architetturali

- [ ] **API REST per tool_agent**: lanciare task via HTTP senza terminale
- [ ] **Notifiche**: avviso quando la run finisce (Telegram, Slack, email)
- [ ] **Log strutturato**: JSON per ogni run, analizzabile per capire dove fallisce
- [ ] **vcap_frames automatico**: MI50 attiva la webcam automaticamente quando
      il task descrive qualcosa di visivo (attualmente va guidato nel prompt)
- [ ] **Timeout thinking per plan_task**: se MI50 non risponde entro N secondi,
      rilanciare la chiamata — previene blocchi su dettagli irrilevanti
- [ ] **MAX_INPUT_TOKENS monitoraggio**: alert automatico se ci si avvicina al limite
      6144 durante una run

---

## 10. Regole operative fondamentali (stabilite 2026-03-19)

### 10.1 Logging persistente di ogni run

Ogni esecuzione del tool_agent produce un archivio completo in:
```
logs/runs/<YYYYMMDD_HHMMSS>_<task_slug>/
├── meta.json              ← task, fqbn, start time
├── run.log                ← log cronologico completo (ogni step, tool, risultato)
├── plan.json              ← output di plan_task e plan_functions
├── checkpoint.json        ← stato serializzato per resume
├── code_v1_generated.ino  ← codice dopo generate_all_functions
├── code_v2_patch1.ino     ← codice dopo ogni ciclo di patch
├── serial_output.txt      ← output seriale dall'ESP32
├── result.json            ← valutazione finale (success, reason, suggestions)
└── frame_000.jpg ...      ← frame webcam catturati
```

**Perché:** avere riscontro storico dell'avanzamento — quali task funzionano,
dove il modello si inceppa, quali errori si ripetono, come migliora nel tempo.

### 10.2 Mai ricominciare da capo

Se una run incontra un errore (tool fallisce, compilazione non converge, upload
bloccato), si corregge il problema e si riprende dall'ultimo checkpoint:

```bash
python agent/tool_agent.py --resume logs/runs/<run_dir> --fqbn esp32:esp32:esp32
```

Il checkpoint viene salvato dopo ogni tool call con successo. Il resume carica
lo stato serializzato e riparte dallo step successivo all'ultimo completato.

**Perché:** le run durano 30-60 minuti tra planning e generazione. Ricominciare
da zero spreca tutto il lavoro già fatto da MI50 e M40.

### 10.3 Smoke test automatico prima di ogni run

Ad ogni avvio di `tool_agent.py`, viene eseguito automaticamente un **smoke test reale**
di tutti i tool (~30 secondi). Se qualcosa non funziona, la run si blocca prima ancora
di chiamare MI50.

I 7 check eseguiti:
1. **compile_sketch**: compila uno sketch minimale (`void setup(){} void loop(){}`) con arduino-cli
2. **remote_uploader**: verifica SSH al Raspberry Pi (`is_reachable()`)
3. **grab_now**: cattura 1 frame reale dalla webcam CSI del Raspberry
4. **evaluate_text**: verifica firma `Evaluator.evaluate()` + health MI50
5. **evaluate_visual**: `docker exec mi50-server python3 -c "import torchvision"` (verifica torchvision senza inferenza)
6. **knowledge DB**: scrive e legge uno snippet di test (`add_snippet()` + `search_snippets_text()`)
7. **extract_patterns**: verifica firma `Learner.extract_patterns(task, code, iterations)`

**Output esempio (tutto OK):**
```
[ToolAgent] ══ PREFLIGHT SMOKE TEST ══
[Preflight] 1/7 compile_sketch — sketch minimale...
  → compile: OK
[Preflight] 2/7 remote_uploader — SSH raggiungibile...
  → Pi: raggiungibile
[Preflight] 3/7 grab_now — cattura 1 frame...
  → grab: /tmp/grab_.../frame_000.jpg
[Preflight] 4/7 evaluate_text — MI50 health + import...
  → evaluate_text firma: OK
[Preflight] 5/7 evaluate_visual — torchvision nel container Docker...
  → torchvision: OK 0.20.1+rocm6.2
[Preflight] 6/7 knowledge DB — scrivi e leggi snippet...
  → add_snippet: OK
  → search_kb: 1 risultati
[Preflight] 7/7 save_to_kb (extract_patterns signature)...
  → extract_patterns firma: OK
[ToolAgent] ✅ Preflight OK — tutti i tool funzionanti
```

**Perché:** le firme delle funzioni cambiano, i container Docker si aggiornano, il Raspberry Pi
va offline. Meglio sapere subito che qualcosa non va invece di scoprirlo dopo 30 minuti di run.

### 10.4 Container Docker MI50 — torchvision

`evaluate_visual` richiede `torchvision` installato nel processo Flask del container.
La semplice `pip install` a runtime **non funziona** senza restart del processo.

**Procedura corretta dopo modifica al Dockerfile:**
```bash
docker stop mi50-server && docker rm mi50-server
docker build --no-cache -f docker/Dockerfile.mi50 -t mi50-server .
bash docker/run_mi50.sh
```

**Verifica rapida:**
```bash
docker exec mi50-server python3 -c "import torchvision; print('OK', torchvision.__version__)"
```

---

*Manuale aggiornato a ogni sessione — vedi STATO.md per lo stato corrente del progetto.*
