# Knowledge Base — Struttura e utilizzo

L'agente accumula conoscenza su librerie, snippet funzionanti e mappature errore→fix. Ogni run riuscita arricchisce il DB — la run successiva sullo stesso tipo di task sarà più veloce e precisa.

---

## Due livelli di storage

### SQLite — dati strutturati

File: `knowledge/arduino_agent.db`

Schema:

```sql
-- Librerie Arduino note
CREATE TABLE libraries (
    name        TEXT PRIMARY KEY,
    version     TEXT,
    include     TEXT,    -- es. #include <Wire.h>
    install_cmd TEXT,    -- es. arduino-cli lib install "Wire"
    description TEXT,
    source      TEXT     -- "seed" | "learned"
);

-- Snippet di codice funzionante
CREATE TABLE snippets (
    id          TEXT PRIMARY KEY,  -- UUID
    task_description TEXT,
    code        TEXT,
    board       TEXT,              -- FQBN
    libraries   TEXT,              -- JSON array
    tags        TEXT,              -- JSON array
    works       INTEGER DEFAULT 1, -- 0/1
    created_at  TEXT
);

-- Mappature errore compilatore → fix
CREATE TABLE errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT,   -- pattern testuale dell'errore
    cause       TEXT,
    fix         TEXT,
    confirmed   INTEGER DEFAULT 0
);

-- Storico run
CREATE TABLE runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task        TEXT,
    mode        TEXT,
    success     INTEGER,
    iterations  INTEGER,
    final_code  TEXT,
    serial_output TEXT,
    created_at  TEXT
);
```

**Interfaccia**: `knowledge/db.py` — funzioni CRUD usate dall'agente. Il DB non si modifica mai manualmente.

### ChromaDB — ricerca semantica

Directory: `knowledge/chroma/`

Ogni snippet funzionante viene indicizzato con il modello `sentence-transformers/all-MiniLM-L6-v2`. La ricerca avviene per vicinanza semantica: il task in linguaggio naturale viene embeddato e confrontato con gli snippet nel vettore store.

**Interfaccia**: `knowledge/semantic.py` — `index_snippet()` e `search_similar()`.

---

## Flusso di aggiornamento

Il DB viene aggiornato solo dal **Learner** (Fase 6), solo dopo una run con `success=True`:

1. MI50 analizza il codice e identifica librerie usate, pattern riutilizzabili, mappature errore→fix
2. Lo snippet viene salvato in SQLite
3. Lo snippet viene indicizzato in ChromaDB
4. Le librerie nuove vengono aggiunte alla tabella `libraries`
5. Le mappature errore→fix vengono aggiunte alla tabella `errors`

---

## Seed data

Lo script `knowledge/seed_data.py` carica i dati iniziali — librerie Arduino comuni pre-caricate prima della prima run. Eseguito una sola volta durante il setup.

```bash
python knowledge/seed_data.py
```

Librerie presenti nel seed: Wire, SPI, EEPROM, Servo, LiquidCrystal, DHT, OneWire, DallasTemperature, IRremote, Adafruit GFX, SSD1306, FastLED, NewPing, PubSubClient.

---

## Query al DB

`knowledge/query_engine.py` espone due funzioni usate dall'agente:

- `get_context_for_task(task)` → stringa di contesto con snippet e librerie rilevanti
- `find_relevant_context(task)` → dict con liste separate di snippet e librerie

La ricerca combina ChromaDB (semantica) e SQLite (strutturata). Il risultato viene passato al Generator come contesto.
