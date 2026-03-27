# Report — Task Orologio Analogico OLED
**Data:** 2026-03-27
**Run dir:** `logs/runs/20260327_053934_Sketch_ESP32_con_OLED_SSD1306_128x64_di/`
**Esito:** ✅ Compilato e caricato — ⚠️ Bug logici nel codice

---

## 1. Il Task

```
Sketch ESP32 con OLED SSD1306 128x64: disegna un orologio analogico animato.
- Lancette ore, minuti, secondi che ruotano in tempo reale usando millis()
- Quadrante con 12 tacche per le ore
- Aggiornamento ogni 1000ms, nessun delay() nel loop
- Mostra anche orario digitale HH:MM:SS in basso (testo size 1)
- Usa Wire.h, Adafruit_GFX.h, Adafruit_SSD1306.h
- OLED: SDA=GPIO21, SCL=GPIO22, addr=0x3C, rst=-1
- Serial.begin(115200), stampa ogni secondo: TIME: HH:MM:SS
```

**Scopo didattico:** verificare se il programmatore funziona su task di sola grafica
(nessun sensore esterno), con librerie note (Adafruit SSD1306 che conosce bene).

---

## 2. Lessons KB trovate da MI50 (search_lessons)

**Query usata:** `"analog clock oled esp32 millis update"` — cercata autonomamente da MI50 al step 1, prima di pianificare.

**Risultato:** 5 lessons trovate, nessuna specifica su orologi. Le lessons rilevanti erano quelle generiche OLED e ESP32 già note:

| Lesson trovata | Applicata da MI50? |
|----------------|-------------------|
| OLED costruttore: 4° param è rst_pin non I2C addr → `-1` | ✅ Sì, incluso nel piano |
| Wire.begin() prima di display.begin() | ✅ Sì, nel setup |
| ESP32 WDT reset se loop > 1s senza yield | ⚠️ Parzialmente (usa millis ma display fuori dall'if) |
| randomSeed (irrilevante) | ✅ Ignorata |
| OLED SSD1306 init con check fallimento | ✅ Sì, `while(1)` se init fallisce |

**Osservazione:** la query non ha trovato nulla di specifico sugli orologi analogici perché non c'è materiale in KB. MI50 ha comunque estratto e applicato correttamente le lessons di contorno (OLED init, Wire.begin). Questo è un comportamento positivo.

---

## 3. Ragionamento MI50 — step per step

### Step 1 — search_lessons
> *"Let me start with search_lessons to check for anti-patterns before planning."*

MI50 cerca proattivamente nella KB prima ancora di pianificare. Identifica correttamente 3 anti-pattern dall'output ricevuto:
1. Costruttore OLED: 4° param = rst_pin non I2C
2. Wire.begin prima di display.begin
3. WDT ESP32 se loop troppo lungo

**Giudizio: ✅ comportamento eccellente — cerca prima di agire.**

---

### Step 2 — plan_task
MI50 produce un piano strutturato e corretto:

```json
{
  "approach": "I2C su ESP32 (SDA=21, SCL=22), SSD1306 addr 0x3C",
  "libraries_needed": ["Adafruit_SSD1306", "Adafruit-GFX-Library"],
  "key_points": [
    "Wire.begin(21, 22) in setup",
    "display.begin(SSD1306_SWITCHCAPVCC, 0x3C) con check di successo",
    "disegna quadrante e tacche ore (12 posizioni)",
    "calcola angoli lancette da millis()",
    "Serial.println() orario ogni secondo"
  ]
}
```

**Giudizio: ✅ piano corretto e completo.**

---

### Step 3 — plan_functions
MI50 decompone in 8 funzioni con firme e compiti precisi:

| Funzione | Firma pianificata | Corretta? |
|---------|------------------|-----------|
| `setup` | `void setup()` | ✅ |
| `getHours` | `int getHours()` | ✅ |
| `getMinutes` | `int getMinutes()` | ✅ |
| `getSeconds` | `int getSeconds()` | ✅ |
| `drawAnalogClock` | `void drawAnalogClock(int h, int m, int s)` | ✅ |
| `drawDigitalTime` | `void drawDigitalTime(int h, int m, int s)` | ✅ |
| `updateTime` | `void updateTime()` | ⚠️ *MI50 la pianifica `void` ma nella descrizione dice "restituisce true/false"* |
| `loop` | `void loop()` | ✅ |

**Limite identificato:** il `compito` di `updateTime` dice "restituisce true/false per indicare se l'aggiornamento è avvenuto" ma la firma è `void`. Questa incoerenza nella descrizione ha confuso M40 che ha generato la funzione con `return true/false` in un `void`. MI50 non ha verificato la coerenza firma/descrizione.

**Giudizio: ⚠️ piano quasi corretto, inconsistenza firma/descrizione in una funzione.**

---

### Steps 6-9 — Debug compilazione
Dopo gli errori di compilazione, MI50 analizza correttamente:

> *"return-statement with a value, in function returning 'void'... La funzione che contiene return true/false ha firma void. Devo rimuovere i return booleani o cambiare la firma."*

> *"variable or field 'updateTime' declared void... updateTime è stato dichiarato come variabile invece che come funzione. Manca la parentesi ()."*

**Giudizio: ✅ diagnosi corretta di entrambi gli errori. Chiama patch_code con analisi precisa.**

---

### Step 11 — Upload
Dopo compilazione OK, MI50 chiama subito upload_and_read senza perdere passi.

**Giudizio: ✅ flusso rispettato.**

---

## 4. Prompt passati a M40 e suo output

### 4a. generate_globals
**Prompt di contesto:** globals_hint da piano MI50 + task description + SYSTEM_GLOBALS

**Output M40:**
```cpp
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_W 128
#define SCREEN_H 64
#define I2C_ADDR 0x3C
#define UPDATE_MS 1000

Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);
unsigned long lastUpdate = 0;
int hour = 0, minute = 0, second = 0;
unsigned long lastSerialTime = 0;
```
**Giudizio M40 globals: ✅ corretto, include giusti, costruttore corretto con -1.**

---

### 4b. generate_all_functions (parallelo)

Generazione in parallelo su 8 funzioni. Problemi di misallineamento tra thread:

**setup() — ✅ corretto**
```cpp
void setup() {
  Wire.begin(21, 22);
  Serial.begin(115200);
  if (!display.begin(SSD1306_SWITCHCAPVCC, I2C_ADDR)) {
    Serial.println("display init failed");
    while (1);
  }
  display.clearDisplay();
  display.display();
}
```

**getHours/getMinutes/getSeconds() — ✅ corretti**
```cpp
int getHours()   { return (millis() / (1000*60*60)) % 24; }
int getMinutes() { return (millis() / (1000*60)) % 60; }
int getSeconds() { return (millis() / 1000) % 60; }
```

**updateTime() — ❌ BUG TIPO RITORNO**
```cpp
// M40 ha generato void ma con return true/false:
void updateTime() {
  if (currentMillis - lastUpdate >= UPDATE_MS) {
    ...
    return true;   // ← ERRORE: void non può restituire valore
  }
  return false;    // ← ERRORE
}
```

**drawAnalogClock() — ⚠️ 3 bug logici (non di compilazione)**
```cpp
void drawAnalogClock(int h, int m, int s) {
  display.clearDisplay();     // ← clearDisplay QUI e anche in loop() → doppio clear
  ...
  // BUG 1: calcolo lancette usa cos() sia per X che per Y
  int hourX = SCREEN_W/2 + cos(hourAngle * PI/180) * 25;
  int hourY = SCREEN_H/2 - cos(hourAngle * PI/180) * 25;  // ← doveva essere sin()!
  // BUG 2: stesso errore per minuteX/Y e secondX/Y
  ...
  display.display();          // ← display() QUI e anche in loop() → doppio display
}
```

**loop() — ⚠️ struttura errata**
```cpp
void loop() {
  // display.clearDisplay() chiamato sia qui che dentro drawAnalogClock()
  display.clearDisplay();         // ← cancella tutto
  drawAnalogClock(...);           // ← disegna orologio + display()
  drawDigitalTime(...);           // ← aggiunge testo (ma clearDisplay lo aveva già cancellato)
  display.display();              // ← secondo display()
}
```

---

## 5. Bug trovati — riepilogo

| # | Bug | Trovato da | Come risolto |
|---|-----|-----------|--------------|
| 1 | `updateTime()` void con `return true/false` | Compiler → MI50 | patch_code (1 iterazione) |
| 2 | `void updateTime;` senza `()` nella forward declaration | Compiler → MI50 | patch_code (2a iterazione) |
| 3 | `cos()` usato sia per X che per Y nelle lancette — doveva essere `sin()` per Y | ❌ Non trovato | Non corretto — bug logico visibile sull'hardware |
| 4 | `clearDisplay()` chiamato due volte (dentro drawAnalogClock E in loop) | ❌ Non trovato | Non corretto |
| 5 | `display()` chiamato due volte (dentro drawAnalogClock E in loop) | ❌ Non trovato | Non corretto |
| 6 | Orario digitale ha formato `0:5` invece di `00:05` (senza zero padding) | ❌ Non trovato | Non corretto |
| 7 | `display.clearDisplay()` e disegno fuori dall'`if millis()` → loop() ridisegna ogni frame senza rate limiting visivo | ❌ Non trovato | Non corretto |

**Bug di compilazione:** 2 trovati e corretti in 2 patch.
**Bug logici:** 5 non rilevati dal sistema — sarebbero visibili sull'hardware (lancette ferme/sbagliate, flickering).

---

## 6. Codice finale prodotto (v3 dopo 2 patch)

```cpp
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_W 128
#define SCREEN_H 64
#define I2C_ADDR 0x3C
#define UPDATE_MS 1000

Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);
unsigned long lastUpdate = 0;
int hour = 0, minute = 0, second = 0;
unsigned long lastSerialTime = 0;

// ... [funzioni getHours/Minutes/Seconds corrette]

void drawAnalogClock(int h, int m, int s) {
  display.clearDisplay();                  // ← clearDisplay DUPLICATO con loop()
  for (int i = 0; i < 12; i++) {
    int x_tick = 64 + cos((i*30-90) * PI/180) * 20;
    int y_tick = 22 + sin((i*30-90) * PI/180) * 20;  // y base = 22, non 32
    display.drawPixel(x_tick, y_tick, SSD1306_WHITE);
  }
  float hourAngle   = (h%12 + m/5.0) * 30 - 90;
  float minuteAngle = (m + s/60.0) * 6 - 90;
  float secondAngle = s * 6 - 90;

  // BUG: usa cos() per Y invece di sin()
  display.drawLine(64, 32, 64 + cos(hourAngle*PI/180)*25,
                            32 - cos(hourAngle*PI/180)*25, SSD1306_WHITE);
  display.display();                       // ← display() DUPLICATO con loop()
}

void loop() {
  display.clearDisplay();                  // ← doppio clear
  drawAnalogClock(getHours(), getMinutes(), getSeconds());
  drawDigitalTime(getHours(), getMinutes(), getSeconds());
  display.display();                       // ← doppio display
  // Serial ogni secondo: funziona correttamente
}
```

**Output seriale:** `TIME: 0:0:5`, `TIME: 0:0:6`... — il contatore secondi avanza correttamente.
**Output OLED:** lancette probabilmente ferme (cos/cos invece di cos/sin), quadrante spostato, flickering.

---

## 7. Analisi — il programmatore usa il bagaglio culturale?

### MI50: usa la KB intelligentemente ✅ con limiti ⚠️

**Cosa ha fatto bene:**
- Ha cercato la KB PRIMA di pianificare, autonomamente
- Ha estratto e applicato le lessons trovate (costruttore OLED, Wire.begin, check init)
- Ha diagnosticato correttamente i 2 errori di compilazione
- Ha seguito il flusso ReAct senza perdere step

**Dove non arriva:**
- Non verifica la coerenza tra firma e descrizione delle funzioni nel piano
- Non identifica i bug logici nel codice (cos/cos, double clear) — li vede come stringa, non li simula
- Non cerca lessons su "trigonometria lancette" perché non sa che mancano

---

### M40: bagaglio culturale buono sulle API, debole sulla logica ⚠️

**Cosa sa bene:**
- Include corretti per Adafruit SSD1306 ✅
- Costruttore `display(W, H, &Wire, -1)` ✅
- Struttura millis() per timing ✅
- API display (drawLine, drawPixel, setTextSize, setCursor) ✅

**Dove sbaglia:**
- Trigonometria: usa `cos()` sia per X che per Y (doveva essere `sin()` per Y) — errore classico di chi conosce la formula ma non la impara a fondo
- Architettura: clearDisplay/display() duplicati perché funzioni indipendenti non "parlano" tra loro
- Firma `void` con `return bool` — riflette l'inconsistenza nel piano di MI50

---

### Conclusione generale

| Aspetto | Risultato |
|---------|-----------|
| Ricerca KB proattiva | ✅ MI50 cerca prima di agire |
| Applicazione lessons trovate | ✅ applica correttamente ciò che trova |
| Riconoscimento gap KB | ❌ non sa quando manca materiale |
| Correzione errori compilazione | ✅ 2 su 2 in 2 patch |
| Rilevamento bug logici | ❌ 0 su 5 trovati |
| Qualità codice M40 su librerie note | ⚠️ API OK, logica a volte sbagliata |
| Autonomia end-to-end | ⚠️ compila e carica, ma codice con bug visivi |

**Il programmatore sa districarsi tra librerie ed errori di compilazione.**
**Non sa ancora ragionare sulla correttezza logica del codice che M40 produce.**
**Il suo "bagaglio culturale" è forte sulle API, debole sulla geometria/architettura.**

---

## 8. Cosa serve per migliorare

1. **KB lessons su trigonometria grafica OLED** — `cos()` per X, `sin()` per Y, centro orologio, lancette
2. **MI50 dovrebbe fare code review** dopo generate_all_functions, prima di compilare — non solo passare il codice direttamente al compilatore
3. **Coerenza piano-firma** — MI50 deve validare che descrizione e firma di ogni funzione siano allineate prima di passare a M40

---

## 9. Analisi visiva — frame dalla webcam

**Run dir:** `logs/runs/20260327_053934_.../frame_000.jpg` (e frame_001, frame_002)

### 9a. Frame 0 — 0:11:21

![frame_000](../logs/runs/20260327_053934_Sketch_ESP32_con_OLED_SSD1306_128x64_di/frame_000.jpg)

### 9b. Frame 1 — 0:11:23

![frame_001](../logs/runs/20260327_053934_Sketch_ESP32_con_OLED_SSD1306_128x64_di/frame_001.jpg)

### 9c. Frame 2 — 0:11:26

![frame_002](../logs/runs/20260327_053934_Sketch_ESP32_con_OLED_SSD1306_128x64_di/frame_002.jpg)

---

### 9d. Cosa confermano le foto — bug theory vs realtà hardware

| Bug teorizzato nel report | Visibile nelle foto? | Note |
|---------------------------|----------------------|------|
| **Bug 3** — `cos()` usato per Y invece di `sin()` → lancette sbagliate | ✅ **CONFERMATO** | Solo UNA lancetta visibile: tutte e 3 si sovrappongono perché con cos/cos puntano nella stessa direzione a distanza diversa |
| **Bug 4/5** — `clearDisplay()` e `display()` duplicati → flickering | ⚠️ Non rilevabile da still | Non rilevabile da foto statica; il display non è completamente nero quindi disegna qualcosa |
| **Bug 6** — zero padding mancante (`0:11:21` invece di `00:11:21`) | ✅ **CONFERMATO** | Chiaramente visibile: `0:11:21`, `0:11:23`, `0:11:26` |
| **Bug 7** — quadrante traslato (tacche centrate a y=22, lancette a y=32) | ✅ **VISIBILE** | Le tacche formano una corona spostata verso l'alto rispetto al centro del display; le lancette partono da più in basso |
| **Nuovo** — LED rosso ESP32 a destra del display | ⚠️ Artefatto camera | Il blob rosso NON è parte dello sketch — è il LED built-in del board ESP32 (GPIO2) illuminato, visibile perché la camera è puntata vicina. Non influenza il display. |

### 9e. Cosa funziona

- **Il tempo avanza correttamente**: frame_000 (0:11:21) → frame_001 (0:11:23) → frame_002 (0:11:26) — i secondi avanzano di 2-3 secondi tra un frame e l'altro, coerente con il timing della webcam
- **Il quadrante è presente**: 12 punti visibili, disposti in cerchio — `drawPixel` in loop funziona
- **La lancetta (singola visibile) si muove**: tra i 3 frame la direzione cambia leggermente → il calcolo `millis()` funziona
- **Il testo digitale è leggibile**: font size 1 in basso a sinistra, chiaramente visibile

### 9f. Osservazione rilevante — il programmatore non sa vedere i suoi errori

Il sistema di valutazione (`evaluate_visual`) aveva già dichiarato il task come successo
perché vedeva "pixel bianchi sul display, testo visibile, oggetti presenti".
**Questo è il limite fondamentale**: la pipeline visiva può confermare che *qualcosa disegna*,
non che *disegna bene*.

Il `request_review` umano avrebbe rilevato immediatamente guardando la foto:
- "ci sono 3 lancette nel codice ma ne vedo solo 1"
- "il tempo digitale ha `0:11:21` senza zero padding"
- "il quadrante è fuori centro"

---

## 10. Prossimo task — test del nuovo flusso con request_review

**Obiettivo:** Rilanciare lo stesso task orologio analogico con il nuovo flusso
che include `request_review` obbligatorio al passo 4.5.

**Ipotesi di miglioramento attesa:**

| Punto | Prima (senza review) | Dopo (con request_review) |
|-------|---------------------|--------------------------|
| Bug cos/cos | Non trovato (0/5 bug logici) | Trovato se reviewer vede il codice |
| Doppio clearDisplay | Non trovato | Trovato se reviewer analizza architettura |
| Zero padding | Non trovato | Trovato facilmente |
| Conversione in lesson KB | Solo errori compilazione | Bug logici confermati → lessons permanenti |

**Note di Claude:**

> Il `request_review` ha senso SOLO se il reviewer (umano o altro agente) è in grado
> di leggere il codice generato e identificare bug logici che il compilatore non trova.
> Il valore aggiunto è: (a) trovare bug prima del caricamento hardware, (b) trasformare
> quei bug in lessons KB permanenti per M40. Anche UN solo reviewer round che trova
> cos/cos vale 10 run di test.

> **Suggerimento per prossima sessione**: lanciare il task orologio con `--max-steps 40`
> per dare spazio al nuovo passo 4.5, e preparare mentalmente i BUG/FIX da inserire
> in `workspace/review_response.txt` quando richiesto.

> Formato risposta review per questo task specifico:
> ```
> BUG: usa cos() per Y nelle lancette invece di sin() | FIX: cambiare tutte le righe tipo "int hourY = SCREEN_H/2 - cos(..." in "int hourY = SCREEN_H/2 - sin(..."
> BUG: clearDisplay() e display() chiamati sia dentro drawAnalogClock che in loop() | FIX: rimuovere clearDisplay() e display() da dentro drawAnalogClock, gestirli solo in loop()
> BUG: orario digitale senza zero padding | FIX: usare String(h < 10 ? "0" : "") + String(h) per h, m, s
> ```

---

## 11. Intervento sistemico — sessione 2026-03-27 pomeriggio

### 11a. Cosa è stato fatto dopo il primo run

**Analisi frame:** lettura dei 3 frame dalla webcam → conferma visiva di 4/5 bug logici:
- `cos/cos` per lancette: **confermato** (una sola lancetta visibile per sovrapposizione)
- zero padding: **confermato** (`0:11:21`)
- offset quadrante/lancette: **confermato** (tacche a y=22, lancette da y=32)
- doppio clearDisplay: **non rilevabile** da still foto

**KB aggiornata (+5 lessons `oled_trigonometry`):**
```
cos per X, sin per Y — errore classico M40
angoli orologio: step×gradi -90, conversione rad
clearDisplay/display solo in loop(), mai in drawXxx()
cx/cy identico per tacche e lancette
zero padding per orario digitale (sprintf o ternary)
```

**Nuova feature implementata — `request_review`:**
- `agent/tool_agent.py`: funzione `_request_review()` + registrata in `_REGISTRY`
- Step 4.5 nel prompt `_SYSTEM`: OBBLIGATORIO dopo `generate_all_functions`, prima di `compile`
- Meccanismo: scrive `workspace/review_request.md` → attende `workspace/review_response.txt` (timeout 10 min)
- Formato feedback: `BUG: ... | FIX: ...` → parsato → `sess.review_notes`
- `_save_to_kb`: se `review_notes` non vuoto → ogni bug+fix diventa lesson `task_type=review_fix` in KB
- Bug fix: f-string con backslash → estratto in variabile `esempio_line`

### 11b. Run v3b — SUCCESSO (2026-03-27)

**Run directory:** `logs/runs/20260327_081258_Sketch_ESP32_con_OLED_SSD1306_128x64_or/`

**Risultato hardware confermato dai frame webcam:**

| Frame | Orario digitale | Lancette | Movimento |
|-------|----------------|---------|-----------|
| frame_000 | `00:09:32` ✅ | 2 lancette visibili ✅ | — |
| frame_001 | `00:09:34` ✅ | 2 lancette, posizione diversa ✅ | +2s |
| frame_002 | `00:09:36` ✅ | 2 lancette, posizione diversa ✅ | +2s |

**Vs v1 (4 bug logici):**
| Bug | v1 | v3b |
|-----|-----|-----|
| cos/cos lancette | ❌ 1 sola visibile | ✅ 2 lancette distinte |
| drawString non esiste | ❌ compile error | ✅ setCursor+print |
| clearDisplay dentro draw | ❌ flickering | ✅ solo in loop() |
| zero padding mancante | ❌ 0:9:5 | ✅ 00:09:32 |

**Zero patch necessarie** — M40 ha generato codice corretto dalla prima iterazione grazie a:
- 6 lessons KB per funzione (oled_trigonometry, oled_ssd1306)
- Regole API esplicite in SYSTEM_FUNCTION (drawString NON ESISTE, snprintf per zero padding)
- Architettura multi-funzione (clearDisplay solo in loop())

**Bug observer rilevato (falso negativo):** M40 observer ha generato report JSON troncato (max_tokens=600 insufficiente per JSON con 19 segmenti). Parser ha fallito → `success_hint=False` → M40 judge ha giudicato "incompleto".

**Fix applicato (post-run):**
- `agent/occhio/observer.py`: `max_tokens=1500` per ultimi 2 passi dell'observer
- Fallback report dai dati accumulati durante i tool calls (check_display_on, detect_motion, read_text)
- OCR override: se `read_text` trova HH:MM:SS → `success_hint=True` automatico
- Keyword orologio/lancett/clock aggiunte alla lista animazioni per motion override
- `compact_hint`: avvisa M40 di non includere arrays dots/segments nel report finale
