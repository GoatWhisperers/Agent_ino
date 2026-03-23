# Prompt — Genera Lessons per la KB di Agent_ino

Copia questo prompt in una chat con un LLM (Claude, GPT-4, ecc.) specificando
l'argomento da esplorare. L'LLM produrrà un JSON pronto da importare nella KB.

---

## PROMPT DA COPIARE

```
Sei un esperto di programmazione Arduino/ESP32 con anni di esperienza pratica.

Il tuo compito: generare una lista di "lessons" per una knowledge base di un agente
AI che genera codice Arduino. Le lessons servono a evitare bug ricorrenti e guidare
la generazione di codice corretto.

## ARGOMENTO DA ANALIZZARE
[INSERISCI QUI: es. "interrupt su ESP32 e Arduino AVR", "sensori I2C (MPU6050, BME280)",
"comunicazione seriale avanzata", "gestione motori stepper", "WiFi ESP32",
"display TFT ST7735/ILI9341", "repo GitHub: github.com/PaoloAliverti/..."]

## FORMATO OUTPUT

Produci SOLO un array JSON valido, senza testo prima o dopo. Ogni elemento:

{
  "task_type": "categoria_breve",   // snake_case, es: "interrupt", "wifi_esp32", "stepper_motor"
  "lesson": "TESTO LESSON",         // REGOLA CRITICA in maiuscolo + spiegazione precisa.
                                    // Deve contenere nomi esatti di funzioni/variabili/pattern.
                                    // Max 400 caratteri.
  "spec_hint": "perché è importante o cosa succede se non si segue",  // può essere null
  "hardware_quirk": "nota hardware specifica",  // può essere null
  "board": "esp32:esp32:esp32" | "arduino:avr:uno" | ""  // vuoto = valido per entrambe
}

## REGOLE PER SCRIVERE LESSONS BUONE

1. Ogni lesson deve essere ACTIONABLE — dice cosa fare o non fare, non solo un concetto
2. Includi il NOME ESATTO della funzione/variabile/costante (attachInterrupt, IRAM_ATTR, volatile, ecc.)
3. Scrivi l'ANTI-PATTERN in spec_hint: cosa genera il bug se non si segue la regola
4. Una lesson = un concetto. Non accorpare 3 cose diverse in una lesson.
5. Le lessons migliori hanno un esempio minimo di codice inline (una riga o due)
6. task_type deve essere specifico: "interrupt_encoder" meglio di "interrupt"

## ESEMPI DI LESSONS BUONE (riferimento per il formato)

{
  "task_type": "interrupt",
  "lesson": "INTERRUPT ISR BREVE: l'ISR deve fare solo set flag o incrementa contatore. MAI Serial.print(), delay(), millis() dentro ISR. Il lavoro vero va nel loop() quando si controlla il flag.",
  "spec_hint": "Serial.print() dentro ISR causa crash su ESP32 perché Serial usa interrupt interni",
  "hardware_quirk": null,
  "board": ""
}

{
  "task_type": "timer_nonbloccante",
  "lesson": "MILLIS OVERFLOW: il pattern 'now-lastTime>=INTERVAL' gestisce l'overflow automaticamente. MAI 'now>=lastTime+INTERVAL' — fallisce dopo 49 giorni quando millis() torna a 0.",
  "spec_hint": "matematica unsigned: 0 - 0xFFFFFFFF = 1 (corretto). lastTime+INTERVAL può overfloware e diventare piccolo.",
  "hardware_quirk": null,
  "board": ""
}

## QUANTE LESSONS

Genera tra 15 e 30 lessons sull'argomento richiesto. Priorità:
- Bug frequenti e non ovvi (alta priorità)
- Differenze ESP32 vs AVR per lo stesso argomento (alta priorità)
- Pattern corretti con esempio codice (media priorità)
- Note hardware specifiche (bassa priorità)

Produci SOLO il JSON array. Inizia con [ e finisci con ]
```

---

## COME USARLO

1. Copia il prompt qui sopra in una chat LLM
2. Sostituisci `[INSERISCI QUI]` con l'argomento
3. L'LLM produce un JSON array
4. Salva il JSON in un file, es: `lessons_interrupt.json`
5. Importalo con questo script Python:

```python
# import_lessons.py
import json
import sys
sys.path.insert(0, '/home/lele/codex-openai/programmatore_di_arduini')

from knowledge.db import add_lesson

with open(sys.argv[1]) as f:
    lessons = json.load(f)

count = 0
for l in lessons:
    try:
        add_lesson(
            task_type=l['task_type'],
            lesson=l['lesson'],
            spec_hint=l.get('spec_hint'),
            hardware_quirk=l.get('hardware_quirk'),
            board=l.get('board', ''),
        )
        count += 1
        print(f"✓ [{l['task_type']}] {l['lesson'][:60]}...")
    except Exception as e:
        print(f"✗ {e}")

print(f"\n{count}/{len(lessons)} lessons importate")
```

```bash
cd /home/lele/codex-openai/programmatore_di_arduini
source .venv/bin/activate
python import_lessons.py lessons_interrupt.json
```

---

## ARGOMENTI SUGGERITI DA ESPLORARE

### Da fare manualmente (esperienza diretta con il sistema):
- `WiFi ESP32` — connect, reconnect, OTA update
- `Sensori I2C` — MPU6050, BME280, DS3231, AHT10
- `Display TFT` — ST7735, ILI9341, differenze da SSD1306
- `Motori` — stepper con A4988/TMC2208, servo, DC con L298N
- `Comunicazione` — UART multi-device, SPI, I2S audio
- `NeoPixel/WS2812B` — FastLED, timing critico, corrente
- `Deep sleep ESP32` — modalità sleep, wakeup sources, RTC memory
- `BLE/ESP-NOW` — comunicazione wireless locale

### Da estrarre da GitHub Paolo Aliverti:
Cerca i suoi repo Arduino e per ogni sketch estrai:
- Pattern usati (state machine, timer, ecc.)
- Errori commentati nel codice
- Workaround hardware documentati
- Librerie preferite e configurazioni

Il prompt sopra funziona anche così:
```
[INSERISCI QUI: analizza questo codice Arduino e estrai lessons:
<incolla codice>
]
```
