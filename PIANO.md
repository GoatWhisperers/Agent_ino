# Piano — Agente Autonomo Programmatore di Arduini

Data: 2026-03-08

---

## Visione

Un agente che riceve un task in linguaggio naturale ("fai lampeggiare un LED
ogni 500ms e stampa un contatore sulla seriale") e da solo:
1. **Prima guarda cosa esiste** — cerca codice analogo nel DB e nel workspace
2. Se trova qualcosa di simile, lo analizza e lo usa come base
3. Progetta il codice (da zero o adattando quello trovato)
4. Lo compila
5. Fa debug in loop se ci sono errori
6. Lo carica sulla scheda
7. Legge l'output dalla seriale
8. Valuta se il comportamento corrisponde al task
9. Se no, riscrive e riprova
10. Quando funziona, impara e aggiorna il suo database

Modalità operative:
- **NEW**: task nuovo, parte da zero (ma guarda sempre il DB prima)
- **CONTINUE**: riprende un progetto esistente, capisce dove era arrivato
- **MODIFY**: modifica un progetto funzionante con nuovi requisiti

Il tutto senza intervento umano. Il thinking dei modelli viene conservato
come log di ragionamento — è parte del processo, non rumore.

---

## Come usiamo le due GPU contemporaneamente

Le due GPU lavorano in parallelo su ruoli diversi e complementari:

```
MI50 (32GB, ROCm)                    M40 (11.5GB, CUDA)
─────────────────                    ─────────────────
Modello: Qwen3.5-9B PyTorch          Modello: Qwen3.5-9B-Q5_K_M GGUF
Ruolo: CERVELLO (lento, profondo)    Ruolo: MANI (veloce, iterativo)
Porta: Python process                Porta: 11435 (llama-server)

- Orchestrazione del task            - Generazione codice Arduino
- Analisi errori compilatore         - Riscrittura rapida dopo errori
- Valutazione output seriale         - Query veloci al database
- Estrazione pattern dal codice      - Formattazione e pulizia codice
- Decisione "funziona / non funziona"
- Aggiornamento knowledge base
```

**Perché questo split:**
- MI50 è lenta ma ha 32GB e fa reasoning profondo con thinking attivo
- M40 fa 18 tok/s — ideale per iterazioni veloci di codice
- I due processi girano in parallelo, comunicano via HTTP e file
- Mentre M40 genera codice, MI50 può già analizzare il task successivo

---

## Architettura

```
┌─────────────────────────────────────────────────────────┐
│                    AGENT LOOP                           │
│                                                         │
│  Task Input (testo naturale)                           │
│       ↓                                                 │
│  [ORCHESTRATOR - MI50]  ←──── Knowledge DB             │
│       │ piano + contesto RAG                           │
│       ↓                                                 │
│  [CODE GENERATOR - M40] ←──── Snippet DB               │
│       │ sketch Arduino                                  │
│       ↓                                                 │
│  [COMPILER - arduino-cli]                              │
│       │                                                 │
│    errori? ──yes──→ [ERROR ANALYZER - MI50]            │
│       │                   │ patch                       │
│       │             [PATCHER - M40]                    │
│       │                   │                             │
│       └──────────────────→↓  (max N tentativi)         │
│       │ ok                                              │
│  [UPLOADER - arduino-cli]                              │
│       ↓                                                 │
│  [SERIAL MONITOR]  (legge output scheda)               │
│       ↓                                                 │
│  [EVALUATOR - MI50]  "output == atteso?"               │
│       │                                                 │
│    no ──→ [REWRITER - M40]  → torna a COMPILER        │
│       │                                                 │
│      yes                                                │
│       ↓                                                 │
│  [LEARNER - MI50]  estrae pattern + librerie           │
│       ↓                                                 │
│  [DB UPDATER]  salva nel knowledge base                │
│       ↓                                                 │
│  OUTPUT: codice funzionante + log ragionamento         │
└─────────────────────────────────────────────────────────┘
```

---

## Componenti

### 0. Code Analyst (MI50 — primo passo sempre)
Prima di scrivere una riga di codice, l'agente cerca:
- Nel DB semantico: snippet simili per significato al task
- Nel workspace/completed: progetti finiti con obiettivo analogo
- Nei docs: librerie rilevanti già documentate

Se trova codice analogo, MI50 lo legge e produce una analisi:
"questo sketch fa X, per il nostro task serve adattare Y e Z".
Il generatore M40 riceve questa analisi come contesto — non parte mai
da zero quando esiste già qualcosa di utile.

Se il task è CONTINUE o MODIFY, l'agente:
- Legge il codice esistente nel workspace
- Legge i log dell'ultima run (cosa funzionava, dove era arrivato)
- MI50 produce un "stato del progetto" prima di procedere

### 1. Orchestrator (MI50 — Qwen3.5-9B con thinking)
Il cervello dell'agente. Riceve il task, decide il piano, valuta i risultati.
Usa il thinking attivo — tutto il ragionamento viene loggato.
Implementato come processo Python con transformers.

### 2. Code Generator / Patcher (M40 — llama-server)
Genera e corregge codice Arduino. Veloce, iterativo.
Riceve: task + errori + snippet rilevanti dal DB.
Restituisce: codice Arduino pulito (già estratto dal markdown).

### 3. Compiler (arduino-cli)
Compila il codice `.ino`. Restituisce stdout/stderr strutturati.
La directory di build è temporanea e isolata per ogni run.
Nessuna interazione con hardware finché non compila.

### 4. Uploader + Serial Monitor (arduino-cli + pyserial)
Carica il binario sulla scheda via USB.
Legge la seriale per N secondi e cattura l'output.
L'output raw viene passato all'Evaluator.

### 5. Evaluator (MI50 — reasoning)
Confronta l'output seriale con il task originale.
Decide: "ha raggiunto l'obiettivo?" con spiegazione.
Può richiedere un nuovo ciclo con indicazioni specifiche.

### 6. Knowledge Base (SQLite + ChromaDB)
Due livelli:

**SQLite (strutturato):**
```
libraries(name, version, include, install_cmd, description)
snippets(id, task_type, code, board, works, created_at)
errors(pattern, cause, fix, confirmed)
boards(name, fqbn, upload_port, baud_rate)
```

**ChromaDB (semantico):**
- Snippet indicizzati per significato
- Errori e fix indicizzati per testo
- Documentazione librerie

Query al DB sempre mediate da un LLM — non SQL raw dall'agente,
ma richieste in linguaggio naturale tradotte in query strutturate.

### 7. Learner (MI50)
Dopo ogni successo estrae automaticamente:
- Quale libreria è stata usata e perché
- Pattern di codice riutilizzabili
- Mappature errore→fix verificate
Aggiorna il DB in modo autonomo.

---

## Stack tecnico

| Componente | Tecnologia |
|---|---|
| Orchestrator / Evaluator / Learner | Python + Transformers (MI50) |
| Code Generator / Patcher | llama-server HTTP API (M40) |
| Compiler / Uploader | arduino-cli (subprocess) |
| Serial Monitor | pyserial |
| DB strutturato | SQLite (stdlib, zero dipendenze) |
| DB semantico | ChromaDB + embedding model |
| Embedding | modello piccolo su CPU (e5-small o simile) |
| Comunicazione inter-processo | HTTP + file JSON |
| Log | JSONL strutturato (ogni run = un file) |

---

## Struttura cartelle

```
programmatore_di_arduini/
├── PIANO.md                  ← questo file
├── REGOLE.md                 ← regole operative
├── .venv/                    ← venv isolato
│
├── agent/
│   ├── analyst.py            ← MI50 analisi codice esistente / CONTINUE / MODIFY
│   ├── orchestrator.py       ← MI50 brain
│   ├── generator.py          ← M40 code gen
│   ├── compiler.py           ← arduino-cli wrapper
│   ├── uploader.py           ← upload + serial
│   ├── evaluator.py          ← MI50 valutazione
│   ├── learner.py            ← MI50 estrazione pattern
│   └── loop.py               ← il loop principale (NEW / CONTINUE / MODIFY)
│
├── knowledge/
│   ├── db.py                 ← interfaccia SQLite + ChromaDB
│   ├── arduino_agent.db      ← SQLite
│   ├── chroma/               ← ChromaDB files
│   └── docs/                 ← documentazione raw (markdown)
│
├── workspace/
│   ├── current/              ← sketch in lavorazione
│   └── completed/            ← sketch funzionanti salvati
│
├── logs/
│   └── run_YYYYMMDD_HHMMSS.jsonl
│
├── test_mi50_qwen35.py       ← test MI50 (già fatto)
├── test_m40_qwen35.py        ← test M40 (già fatto)
└── avvia_qwen35.sh
```

---

## TODO List

### FASE 0 — Setup (prerequisiti)
- [ ] 0.1 Installare arduino-cli nel venv e verificare funzionamento
- [ ] 0.2 Configurare la scheda Arduino (FQBN, porta USB)
- [ ] 0.3 Installare pyserial nel venv
- [ ] 0.4 Creare struttura cartelle del progetto

### FASE 1 — Compiler wrapper
- [ ] 1.1 `compiler.py`: compila uno sketch .ino, restituisce dict con
         `{success, errors, warnings, binary_path}`
- [ ] 1.2 Parser errori arduino-cli → struttura dati con riga, tipo, messaggio
- [ ] 1.3 Test: compila uno sketch funzionante, uno rotto, uno con warning

### FASE 2 — Code Generator (M40)
- [ ] 2.1 `generator.py`: chiama M40 via HTTP, riceve task + contesto,
         restituisce codice Arduino pulito (markdown rimosso)
- [ ] 2.2 Pulizia automatica output: estrae solo il blocco codice,
         separa thinking dal codice, salva entrambi
- [ ] 2.3 Test: genera sketch LED, verifica che sia codice pulito

### FASE 3 — Orchestrator (MI50)
- [ ] 3.1 `orchestrator.py`: carica Qwen3.5-9B su MI50, espone metodo
         `plan(task) → {approach, libraries_needed, context_queries}`
- [ ] 3.2 Gestione thinking: tutto il contenuto `<think>...</think>`
         viene loggato separatamente
- [ ] 3.3 Test: pianifica un task semplice, verifica output strutturato

### FASE 4 — Knowledge Base
- [ ] 4.1 `db.py`: schema SQLite, CRUD per libraries/snippets/errors/boards
- [ ] 4.2 ChromaDB: indicizzazione snippet, query semantica
- [ ] 4.3 DB query mediata da LLM: "trova snippet per controllo seriale"
         → il modello traduce in query → risultati → contesto
- [ ] 4.4 Caricamento iniziale: documentazione Arduino base, librerie comuni
- [ ] 4.5 Indicizzazione workspace/completed: tutti i progetti finiti
         vengono indicizzati e sono ricercabili semanticamente

### FASE 5 — Error Analyzer + Patcher
- [ ] 5.1 `orchestrator.py`: metodo `analyze_errors(code, errors) → {cause, fix}`
         con thinking attivo
- [ ] 5.2 `generator.py`: metodo `patch(code, analysis) → fixed_code`
- [ ] 5.3 Loop compile→analyze→patch con max 5 tentativi, log di ogni iterazione
- [ ] 5.4 Test: sketch rotto intenzionalmente, verifica auto-fix

### FASE 6 — Uploader + Serial Monitor
- [ ] 6.1 `uploader.py`: upload via arduino-cli, gestione errori porta occupata
- [ ] 6.2 Serial monitor: legge per N secondi, cattura output, gestisce timeout
- [ ] 6.3 Test: carica sketch LED blink, verifica che non si rompa nulla

### FASE 7 — Evaluator
- [ ] 7.1 `evaluator.py`: MI50 confronta output seriale vs task originale
- [ ] 7.2 Restituisce `{success: bool, reason: str, suggestions: str}`
- [ ] 7.3 Test: carica sketch che stampa "ciao", task="stampa ciao ogni secondo"

### FASE 7b — Modalità CONTINUE / MODIFY
- [ ] 7b.1 Rilevamento modalità dal task: "continua il progetto X",
           "modifica lo sketch Y aggiungendo..."
- [ ] 7b.2 `analyst.py`: legge codice esistente + log run precedenti,
           produce stato del progetto (cosa funziona, cosa manca)
- [ ] 7b.3 Il contesto dello stato entra nel loop normale da FASE 2 in poi
- [ ] 7b.4 Test: carica un progetto a metà, chiede di completarlo

### FASE 8 — Loop principale
- [ ] 8.1 `loop.py`: mette insieme tutti i componenti nel loop descritto sopra
- [ ] 8.2 Gestione stati: planning → generating → compiling → uploading →
         evaluating → learning → done
- [ ] 8.3 Log JSONL completo di ogni run (thinking incluso)
- [ ] 8.4 Test end-to-end: task completo da zero

### FASE 9 — Learner
- [ ] 9.1 `learner.py`: dopo successo, MI50 estrae pattern e librerie
- [ ] 9.2 Auto-update del DB: inserisce snippet, aggiorna mappature errori
- [ ] 9.3 Verifica che la seconda run dello stesso task sia più veloce

### FASE 10 — Self-improvement continuo
- [ ] 10.1 Scraper documentazione: Arduino reference + librerie popolari → docs/
- [ ] 10.2 Indicizzazione automatica nuova documentazione
- [ ] 10.3 Meccanismo di feedback: se un fix funziona N volte, aumenta il peso

---

## Workflow di una run completa

```
INPUT: "Leggi la temperatura da un sensore NTC e stampala ogni secondo"

0. [ANALYST MI50 - thinking]
   Cerca nel DB: "NTC temperature read Arduino" → trova sketch simile?
   Cerca in completed/: c'è qualcosa con NTC o sensori analogici?
   Se sì: legge e analizza → "questo sketch legge LDR, la logica analogica
   è la stessa, adatto la formula"
   Se no: parte da zero

1. [ORCHESTRATOR MI50 - thinking]
   Piano: serve NTC + calcolo Steinhart-Hart + Serial.println
   Contesto: eventuale codice analogo trovato nel passo 0

2. [M40 GENERATOR]
   Contesto: task + eventuale snippet NTC dal DB
   Output: sketch.ino pulito

3. [COMPILER]
   arduino-cli compile --fqbn arduino:avr:uno sketch.ino
   → OK oppure errori strutturati

4a. Se errori → [MI50 ANALYZER thinking]
    "errore: 'NTC_PIN' non dichiarato"
    Thinking: "ho dimenticato #define NTC_PIN A0"
    → [M40 PATCHER] → codice corretto → torna a 3

4b. Se OK → [UPLOADER]
    arduino-cli upload → flash sulla scheda

5. [SERIAL MONITOR]
   Legge 10 secondi: "Temperatura: 23.4 C\nTemperatura: 23.5 C\n..."

6. [MI50 EVALUATOR thinking]
   "L'output mostra temperatura in Celsius ogni ~1s. Corrisponde al task."
   → SUCCESS

7. [MI50 LEARNER]
   Estrae: libreria usata (nessuna, calcolo raw), pin NTC, formula
   Salva snippet "NTC_basic_read" nel DB

OUTPUT: codice funzionante + log completo con tutto il thinking
```

---

## Note implementative

- **Parallelismo MI50/M40**: mentre M40 genera codice, MI50 può già
  preparare il contesto per il passo successivo. Usare threading/asyncio.
- **Timeout**: ogni chiamata LLM ha timeout. Se MI50 è lenta, M40 può
  fare una prima analisi veloce in attesa.
- **Max loop**: max 5 cicli compile→fix, max 3 cicli evaluate→rewrite.
  Dopo si arrende e salva il log per analisi manuale.
- **Porta seriale**: rilevata automaticamente con arduino-cli board list.
- **Thinking log**: ogni blocco `<think>` salvato con timestamp, fase,
  modello. Consultabile dopo la run.
- **Il DB non si tocca manualmente** — solo il Learner lo aggiorna,
  su decisione del modello.
