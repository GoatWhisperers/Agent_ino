# Notebook operativo — pattern e generazione per funzione

Documentazione del `Notebook` e del flusso di generazione codice funzione per funzione.

---

## Il problema che risolve

Prima del Notebook, M40 riceveva tutto il contesto del task in un unico prompt e generava l'intero sketch in una volta. Questo causava due problemi:

1. **Contesto troppo corto** — con `--ctx-size 4096`, sketch complessi non entravano nel context window
2. **Qualità bassa** — il modello doveva tenere in mente troppe cose contemporaneamente

La soluzione: **MI50 pianifica, M40 esegue un pezzo alla volta**.

---

## Flusso

```
MI50 (Orchestrator)
  │
  ├─ plan_task()       → approccio, librerie, note_tecniche, vcap_frames
  │
  └─ plan_functions()  → globals_hint + lista funzioni ordinata
         │
         └─ [{nome, firma, compito, dipende_da}, ...]
                │
                ▼
         Notebook.set_funzioni()
                │
                ▼
M40 (Generator) — per ogni funzione in ordine topologico:
  │
  ├─ generate_globals()     → #include, #define, oggetti globali
  ├─ generate_function(f1)  → prima funzione helper
  ├─ generate_function(f2)  → seconda funzione helper (vede f1 nel contesto)
  ├─ generate_function(setup)
  └─ generate_function(loop)
         │
         ▼
  Notebook.assemble()
         │
         ▼
  sketch.ino finale
```

---

## Notebook — struttura dati

Il Notebook è un oggetto Python serializzabile in JSON. Persiste su disco in `workspace/current/<task>/notebook.json` al termine di ogni run.

```json
{
  "task": "su display OLED SSD1306 mostra la temperatura da NTC",
  "board": "esp32:esp32:esp32",
  "created_at": "2026-03-10T14:30:00.000000",
  "piano": ["Wire.begin(21,22)", "display.begin(SSD1306_SWITCHCAPVCC,0x3C)", "..."],
  "dipendenze": ["Adafruit_SSD1306", "Adafruit-GFX-Library"],
  "note_tecniche": ["SDA=GPIO21 SCL=GPIO22", "I2C addr=0x3C", "baud 115200"],
  "globals_hint": "#include <Wire.h>\n#include <Adafruit_SSD1306.h>\nAdafruit_SSD1306 display(128,64,&Wire,-1);",
  "globals_code": "#include <Wire.h>\n#include <Adafruit_SSD1306.h>\n...",
  "funzioni": [
    {
      "nome": "setup",
      "firma": "void setup()",
      "compito": "Wire.begin(21,22), Serial.begin(115200), display.begin()",
      "dipende_da": [],
      "stato": "done",
      "codice": "void setup() {\n  Wire.begin(21, 22);\n  ...\n}"
    },
    {
      "nome": "readTemperature",
      "firma": "float readTemperature()",
      "compito": "legge analogico da A0, converte con Steinhart-Hart",
      "dipende_da": [],
      "stato": "done",
      "codice": "float readTemperature() {\n  ...\n}"
    },
    {
      "nome": "loop",
      "firma": "void loop()",
      "compito": "chiama readTemperature() e showTemp(), delay(1000)",
      "dipende_da": ["readTemperature", "showTemp"],
      "stato": "done",
      "codice": "void loop() {\n  ...\n}"
    }
  ],
  "stato": "done",
  "errori_visti": [
    {"errore": "Adafruit_GFX.h: No such file", "fix": "aggiunto #include <Adafruit_GFX.h>"}
  ],
  "log_fasi": [
    {"fase": "func:setup", "risultato": "done", "ts": "14:31:05"},
    {"fase": "func:loop", "risultato": "done", "ts": "14:32:10"}
  ]
}
```

---

## Ordinamento topologico delle funzioni

`funzioni_ordinate()` usa un topological sort iterativo. Le regole:

1. Una funzione può essere generata quando tutte le sue `dipende_da` sono già `done`
2. `setup()` ha priorità 0 (generata prima)
3. `loop()` ha priorità 999 (generata ultima)
4. Le dipendenze cicliche vengono aggiunte in coda senza crash

**Esempio:**
```
funzioni: [loop, readTemp, showTemp, setup]
dipende_da: loop→[readTemp, showTemp], setup→[], readTemp→[], showTemp→[]

Ordine risultante: setup → readTemp → showTemp → loop
```

---

## Contesto per M40 — `context_for_globals()`

```
TASK: su display OLED SSD1306...
BOARD: esp32:esp32:esp32
NOTE TECNICHE:
  - SDA=GPIO21 SCL=GPIO22
  - I2C addr=0x3C
LIBRERIE DA INCLUDERE: Adafruit_SSD1306, Adafruit-GFX-Library
SUGGERIMENTO GLOBALS: #include <Wire.h>\nAdafruit_SSD1306 display(...)
FUNZIONI CHE SEGUIRANNO (firme):
  void setup();
  float readTemperature();
  void showTemp(float temp);
  void loop();
```

M40 riceve questo e genera solo la sezione globale. Sa che non deve scrivere funzioni.

---

## Contesto per M40 — `context_for_function(nome)`

```
TASK GLOBALE: su display OLED SSD1306...
BOARD: esp32:esp32:esp32
GLOBALS GIÀ SCRITTI:
  #include <Wire.h>
  #include <Adafruit_SSD1306.h>
  Adafruit_SSD1306 display(128, 64, &Wire, -1);
  float lastTemp = 0;
FIRME ALTRE FUNZIONI (già disponibili):
  void setup();
  float readTemperature();
  void loop();
FUNZIONE readTemperature (già scritta, per riferimento):
  float readTemperature() {
    int raw = analogRead(A0);
    ...
  }

FUNZIONE DA SCRIVERE: void showTemp(float temp)
COMPITO: display.clearDisplay(), stampa temp con 1 decimale e unità C, display.display()
NOTE TECNICHE:
  - SDA=GPIO21 SCL=GPIO22
ERRORI GIÀ VISTI (non ripetere):
  • Adafruit_GFX.h: No such file → aggiunto #include <Adafruit_GFX.h>
```

M40 vede esattamente il contesto che gli serve. Niente di più.

---

## Assemblaggio `.ino` finale

`assemble()` produce il file in quest'ordine:

```
1. globals_code          ← #include, #define, variabili globali

2. Forward declarations  ← firma; per ogni helper (non setup/loop)
   float readTemperature();
   void showTemp(float temp);

3. Funzioni in ordine topologico:
   void setup() { ... }
   float readTemperature() { ... }
   void showTemp(float temp) { ... }
   void loop() { ... }
```

Ritorna anche `line_map: dict[nome → riga_inizio]` usato per attribuire errori del compilatore alla funzione responsabile.

---

## Attribuzione errori a funzioni

Quando la compilazione fallisce, `funzione_da_errore(line_map, error_line)` trova la funzione responsabile:

```
line_map = {"setup": 12, "readTemperature": 25, "showTemp": 38, "loop": 52}
error_line = 43  → "showTemp" (ultima con start_line ≤ 43)
```

Questo permette di rigenerare **solo la funzione con errori** invece di riscrivere tutto lo sketch.

---

## Stati delle funzioni

```
pending     ← non ancora generata (stato iniziale)
generating  ← M40 la sta generando
done        ← generata con successo
error       ← errore attribuito a questa funzione
```

La `progress()` produce una barra visiva:
```
✅ setup()   ✅ readTemperature()   ⚙ showTemp()   ⬜ loop()
```

---

## Gestione errori già visti

`errori_visti` è una lista persistente. Ogni volta che viene trovato un errore di compilazione, viene aggiunto:

```python
nb.add_errore("Adafruit_GFX.h: No such file", "aggiunto #include <Adafruit_GFX.h>")
```

Nel contesto per M40 compaiono gli ultimi 3 errori visti con il relativo fix. M40 li legge e non ripete lo stesso errore.

---

## Fallback monolitico

Se `plan_functions()` torna una lista vuota (il modello ha fallito il JSON o il task è banale), il sistema cade automaticamente in modalità monolitica:

```python
if nb.funzioni:
    return _phase_generate_by_function(...)
else:
    return _phase_generate_monolithic(...)
```

La modalità monolitica usa `generate_code()` con tutto il contesto in un unico prompt, max_tokens=2048. Stessa logica di prima del Notebook.

---

## API pubblica

```python
from agent.notebook import Notebook

# Creazione
nb = Notebook(task="...", board="esp32:esp32:esp32")

# Popolamento (da Orchestrator)
nb.set_plan(piano=["step1","step2"], dipendenze=["Lib1"], note_tecniche=["pin=21"])
nb.set_funzioni(globals_hint="...", funzioni=[{...}, {...}])

# Navigazione
for f in nb.funzioni_ordinate():
    print(f["nome"], f["firma"])

# Aggiornamento
nb.globals_code = gen.generate_globals(nb)["code"]
nb.update_funzione("setup", "done", code)
nb.add_errore("errore", "fix applicato")
nb.update_stato("compiling")

# Assemblaggio
code, line_map = nb.assemble()
func_name = nb.funzione_da_errore(line_map, error_line=42)

# Stato
print(nb.summary())    # "[DONE] task... | funzioni=4/4 errori=0"
print(nb.progress())   # "✅ setup()   ✅ loop()"

# Persistenza
nb.save(Path("workspace/current/task/notebook.json"))
nb2 = Notebook.load(Path("workspace/current/task/notebook.json"))
```
