# Report Sessione DHT11 + OLED — 2026-03-27

## Obiettivo

Generare e caricare su ESP32 uno sketch che:
- Legge temperatura e umidità da DHT11 (GPIO27)
- Mostra valori su OLED SSD1306 128x64
- Disegna un gauge semicircolare animato per l'umidità

---

## 1. Valutazione del Programmatore (MI50 + M40)

### MI50 — Reasoning/Planning ✅ SUFFICIENTE

MI50 ha lavorato correttamente nella fase di pianificazione:
- Ha compreso il task completo
- Ha chiamato `plan_task` rispettando la regola "una action per risposta"
- Non ha mai scritto codice direttamente (delega sempre a M40)
- Ha identificato le funzioni giuste: `readSensor`, `drawGauge`, `drawLabels`, `showError`

**Limite riscontrato:** non ha cercato nella KB lessons su DHTesp prima di pianificare
(avrebbe potuto rilevare che DHTesp è una libreria meno conosciuta da M40).

### M40 — Code Generation ❌ INSUFFICIENTE

M40 ha generato 10 versioni di codice senza mai risolvere gli errori di compilazione.
La run è terminata per esaurimento step (30/30) senza produrre codice funzionante.

| Bug generato da M40 | Versione | Gravità |
|---------------------|----------|---------|
| `#include <DHT.h>` invece di `<DHTesp.h>` (task lo specificava) | v1 | 🔴 critico |
| `drawHLine()` — funzione inesistente in Adafruit_GFX | v1 | 🔴 critico |
| `display.setRotation()` usato per ruotare la lancetta (ruota tutto il display) | v1 | 🟠 grave |
| `drawLabels()` chiama `clearDisplay()` internamente (cancella gauge appena disegnato) | v1 | 🟠 grave |
| `loop()` troncato a riga 173 — codice incompleto | v1 | 🔴 critico |
| `drawHLine` non corretto in 8 patch successive | v2→v10 | 🔴 critico |
| `dht.readTemperature()` / `dht.readHumidity()` (API DHT standard, non DHTesp) | v2 | 🔴 critico |

**Diagnosi:** M40 non conosce l'API DHTesp e ha continuato a mischiare l'API della
libreria Adafruit DHT standard con include di DHTesp. Il patcher non è riuscito a
distinguere i due paradigmi.

### Intervento Manuale Claude

Claude ha riscritto lo sketch da zero dopo il fallimento del programmatore:
- Usato `dht.setup(pin, DHTesp::DHT11)` + `dht.getTempAndHumidity()`
- Sostituito `drawHLine` → `drawPixel` in loop per l'arco
- Rimosso `setRotation`, ridisegnata la lancetta con trigonometria corretta
- Corretto il flusso `clearDisplay → drawLabels → drawGauge → display()`

Lo sketch ricompilato ha compilato al primo tentativo ✅.

**Fix sistemici aggiunti al progetto:**
- `compiler.py`: `_fix_drawHLine_to_drawFastHLine()` aggiunto a `_API_ERROR_FIXES`
- KB: lesson `oled_ssd1306 / DRAWFASTHLINE` aggiunta (310 → 311 lessons)

---

## 2. Risultato Hardware — DHT11 non trovato

### Fase 1: Sketch con GPIO27 (come da task)
```
Status: 1 (ERROR_TIMEOUT) — ripetuto ogni 2s
```

### Fase 2: Pin Scanner su 17 GPIO (GPIO 2,4,5,12-19,23,25-27,32,33)
```
Testing GPIO5  ... nok (status=1)
Testing GPIO12 ... nok (status=1)
Testing GPIO13 ... nok (status=1)
...
Testing GPIO27 ... nok (status=1)
Testing GPIO33 ... nok (status=1)
=== SCAN COMPLETE ===
```

**Nessun pin ha risposto.** Status=1 su tutti = `ERROR_TIMEOUT`.

### Diagnosi possibile

| Causa | Probabilità |
|-------|-------------|
| Filo D0 non inserito nel pin GPIO indicato | 🔴 Alta |
| Modulo DHT11 non alimentato (VCC o GND disconnesso) | 🔴 Alta |
| Modulo DHT11 difettoso | 🟡 Media |
| Libreria DHTesp incompatibile con questo modulo | 🟢 Bassa |

Status=1 su TUTTI i pin (incluso GPIO27) indica che la linea dati
è sempre "alta" o "bassa" — non c'è nessun segnale DHT11 su nessun GPIO.
Questo è coerente con un problema di alimentazione del modulo
(se VCC o GND non sono collegati, D0 non produce segnale).

### Prossimi step suggeriti

1. Verifica con multimetro che VCC del modulo misuri ~3.3V rispetto a GND
2. Controlla che il pin D0 del modulo sia inserito saldamente in un GPIO dell'ESP32
3. Se il modulo è il tipo a 4 pin (non 3 pin), verifica che il pin NC (not connected) non sia confuso con D0
4. Prova con la libreria standard `#include <DHT.h>` invece di DHTesp

---

## 3. Stato Finale Sketch

Il codice (`code_v11_manual_fix.ino`) è funzionante e caricato sull'ESP32.
Quando il DHT11 sarà collegato correttamente, il display mostrerà:

```
┌──────────────────────┐
│ DHT11 Monitor        │  ← testo size 1
│ T:24.5C              │  ← testo size 2
│ H:58.0%              │  ← testo size 1
│         .            │
│       /   \          │  ← arco semicircolare
│  0  25 ↑ 75  100    │  ← lancetta + tacche
└──────────────────────┘
```

Seriale atteso:
```
Temp: 24.5 C, Hum: 58.0 %
```

---

## 4. Conclusioni sul Programmatore

| Componente | Giudizio | Note |
|-----------|---------|------|
| MI50 planning | ✅ Sufficiente | Pianifica bene, rispetta il ReAct loop |
| M40 codice (librerie note) | ✅ Buono | Snake, Conway, Boids: 0 errori |
| M40 codice (librerie nuove) | ❌ Insufficiente | DHTesp: 10 patch fallite, errori ripetuti |
| Sistema autonomia end-to-end | ⚠️ Parziale | Funziona su task noti, fallisce su librerie meno diffuse nel training |

**Raccomandazione:** prima di dare a M40 un task con una libreria poco nota,
aggiungere in KB almeno 5-10 lessons specifiche sull'API di quella libreria
(pattern di init, lettura, error handling). Questo è esattamente il caso DHTesp.

---

## 5. Analisi Root Cause — KB e Search

### Cosa c'era in KB prima del task

| Lessons trovate | Libreria | Utili per DHTesp? |
|----------------|----------|-------------------|
| `dht_sensor` — SimpleDHT API | SimpleDHT | ❌ No |
| `dht11_dht22` — 4 lessons generiche | generiche | ⚠️ Parziale |
| **DHTesp API specifica** | **DHTesp** | **❌ Assente** |

### I 3 casi diagnosticati (come da Lele)

| Caso | Situazione | Problema reale |
|------|-----------|----------------|
| 1. Materiale c'è, non sa trovarlo | ❌ Non è questo | search_lessons funziona, ma trova SimpleDHT non DHTesp |
| 2. Materiale assente | ✅ **QUESTO** | KB non aveva lessons DHTesp — M40 ha inventato API |
| 3. Materiale c'è ma struttura sbagliata | ⚠️ Parziale | Lessons generiche non bastano per API specifiche |

### Fix applicato in questa sessione

- ✅ Aggiunte **16 lessons DHTesp** specifiche (task_type: `dhtesp`)
  - `dht.setup(pin, DHTesp::DHT11)` come init corretto
  - `dht.getTempAndHumidity()` → struct `TempAndHumidity`
  - `dht.getStatus()` per error handling
  - Timing: minimo 2s tra letture, delay 1-2s dopo setup

### Lezione generale per il progetto

> **Prima di dare a M40 un task con una libreria specifica, verificare che la KB
> abbia almeno 5 lessons sull'API di quella libreria.**
> Se mancano → eseguire `generate_lessons.py "NomeLibreria API"` prima di lanciare il programmatore.

Questo è il punto critico: **il programmatore è bravo quanto la sua KB**.
M40 non ha accesso a internet durante la generazione — sa solo quello che
è stato iniettato nel prompt dalla KB.

