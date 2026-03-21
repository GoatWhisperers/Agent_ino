# ⚠️ TENTATIVO 1 — FALLITO (2026-03-19)
> **Archiviato il 2026-03-20**
> **Motivo del fallimento:**
> - Display OLED nero in tutti i frame (Wire.begin senza pin, logica duplicata)
> - MI50 ha hallucinato la valutazione visiva: ha dichiarato success=true su display nero
> - Serial output sembrava valido ma era composto da messaggi WALL falsi (stampati ogni 500ms indipendentemente dai veri rimbalzi)
>
> **Fix applicati nel Tentativo 2:** vedi `lezione_3palline.md`

---

# Lezione — Tre palline rimbalzanti con collisioni elastiche su OLED (Tentativo 1)
> Task: animazione OLED SSD1306 128x64 con 3 palline che rimbalzano sui bordi
> e si scontrano tra loro in modo fisicamente realistico (collisione elastica).

---

## Il sistema

Prima di avviare il lavoro, il tool_agent esegue un **preflight smoke test**
che verifica che ogni tool funzioni davvero con una chiamata reale:

```
[Preflight] 1/7 compile_sketch — sketch minimale compilato → OK
[Preflight] 2/7 remote_uploader — SSH Raspberry Pi → raggiungibile
[Preflight] 3/7 grab_now — frame webcam catturato → OK
[Preflight] 4/7 evaluate_text — firma Evaluator + health MI50 → OK
[Preflight] 5/7 evaluate_visual — torchvision nel container Docker → OK 0.20.1+rocm6.2
[Preflight] 6/7 knowledge DB — scrivi + leggi snippet → OK
[Preflight] 7/7 extract_patterns firma → OK
✅ Preflight OK — tutti i tool funzionanti
```

**Perché è importante:** se un tool è rotto (parametro sbagliato, libreria mancante,
Raspberry irraggiungibile) lo scopriamo in 30 secondi invece che a metà run.

---

## I protagonisti

| Modello | Ruolo | Hardware |
|---------|-------|----------|
| **MI50** (Qwen3.5-9B bfloat16, ROCm) | Ragiona, pianifica, coordina, valuta | AMD Radeon MI50 32GB |
| **M40** (Qwen3.5-9B Q5_K_M GGUF, CUDA) | Genera tutto il codice C++ | NVIDIA Tesla M40 24GB |

MI50 è il **direttore**: riceve il task, decide cosa fare passo per passo,
chiama gli strumenti, interpreta i risultati. Non scrive mai codice.

M40 è l'**esecutore**: riceve una specifica precisa da MI50 e genera il codice C++.
Non ragiona sul problema — traduce la specifica in codice.

---

## Il flusso ReAct

L'agente usa un loop **ReAct** (Reason + Act):

```
MI50 pensa → decide un'azione → esegue il tool → osserva il risultato → pensa di nuovo → ...
```

Ogni risposta di MI50 è un singolo JSON:
```json
{"tool": "nome_tool", "args": {...}, "reason": "perché lo faccio"}
```
oppure, quando ha finito:
```json
{"done": true, "success": true, "reason": "spiegazione del risultato"}
```

Il contesto è gestito in stile **MemGPT**: system prompt fisso + ancora fase-specifica
(si adatta alla fase corrente: planning / generating / compiling / uploading / evaluating)
+ sliding window degli ultimi 5 turni.

---

## STEP 1 — MI50 legge il task e pianifica l'azione

**Input al sistema (task dell'utente):**
```
Animazione OLED SSD1306 128x64: tre palline (cerchi pieni raggio 3px) che rimbalzano
sui bordi E si scontrano tra loro in modo realistico (collisione elastica, masse uguali).
Ogni pallina ha posizione e velocità iniziale diversa.
Quando due palline si scontrano (distanza centri <= 6px) scambiano le componenti di
velocità lungo la normale della collisione.
Ogni rimbalzo su bordo stampa WALL_N M (N=pallina, M=contatore).
Ogni collisione tra palline stampa BALL_A_B.
Animazione in loop con millis() senza delay().
HARDWARE: ESP32 NodeMCU OLED I2C SDA=GPIO21 SCL=GPIO22 addr=0x3C.
LIBRERIE: Adafruit_SSD1306 Adafruit_GFX Wire.
```

**MI50 (reasoning interno — Step 1):**

Prima ancora di chiamare un tool, MI50 analizza il task e pianifica l'intero flusso
che dovrà seguire:

```
"The user wants me to create an Arduino/ESP32 program that animates three bouncing
balls on an OLED display. The balls should:
  1. Be circles with 3px radius
  2. Bounce off walls
  3. Collide with each other (elastic collision with equal masses)
  4. Print "WALL_N M" when hitting walls
  5. Print "BALL_A_B" when colliding with each other
  6. Use millis() for timing (no delay())
  7. Display on SSD1306 128x64 OLED at I2C addr=0x3C

This is a physics simulation task with display output. I need to follow the flow:
  1. plan_task
  2. plan_functions
  3. generate_globals
  4. generate_all_functions
  5. compile
  6. upload_and_read
  7. grab_frames → evaluate_visual (since OLED is involved)
  8. save_to_kb
  9. done

Let me start with plan_task."
```

> **Nota didattica:** MI50 non esegue subito — prima mappa il problema sul flusso
> di tool disponibili. Sa già che dovrà usare `evaluate_visual` (non `evaluate_text`)
> perché il task usa un display OLED fisico.

**Azione decisa:**
```json
{
  "tool": "plan_task",
  "args": {},
  "reason": "Inizializzo il piano per l'animazione di 3 palline che rimbalzano
             su OLED SSD1306 con collisioni elastiche"
}
```

---

## STEP 2 — MI50 (Orchestrator) — plan_task

Il tool `plan_task` passa il task all'**Orchestrator** (ancora MI50, ma in un ruolo
separato: architetto software). L'Orchestrator risponde con un piano strutturato in JSON.

**Reasoning dell'Orchestrator (pensiero interno completo):**

```
1. Analyze the Request:
   - Role: Expert Arduino/Embedded Software Architect.
   - Output Format: Valid JSON object ONLY.
   - Task: 3 bouncing balls on OLED SSD1306 (128x64), elastic collisions.

2. Drafting the Content:

   approach: "Simulazione fisica in loop principale con millis(), aggiornamento
             posizioni, rilevamento collisioni bordi e tra palline, redraw display."

   libraries_needed: ["Adafruit_SSD1306", "Adafruit_GFX_Library"]
   (Wire è built-in ESP32, non serve installare)

   key_points:
     1. Wire.begin(21, 22) in setup
     2. display.begin(SSD1306_SWITCHCAPVCC, 0x3C)
     3. Definisci struct Ball { x, y, vx, vy, id, bounceCount }
     4. Inizializza 3 istanze con posizioni e velocità diverse
     5. Loop: updatePositions(), checkBoundaries(), checkCollisions(), drawAll()
     6. Serial.print("WALL_N M") per rimbalzi su bordo
     7. Serial.print("BALL_A_B") per collisioni tra palline

   note_tecniche:
     - SDA=GPIO21, SCL=GPIO22
     - I2C addr=0x3C
     - Raggio cerchio = 3px, collisione quando distanza centri <= 6px
     - Display 128x64, origine (0,0) in alto a sinistra
     - millis() per timing, target ~50ms per frame (20fps)
     - baud 115200

   vcap_frames: 0  ← animazione OLED, nessuna webcam richiesta

3. Self-correction su vcap_frames:
   "The prompt says vcap_frames > 0 only if LED/display/movement visible.
    Since this is an OLED animation, 0 is correct — la webcam viene chiamata
    dopo dall'agent con grab_frames, non dal piano."
```

> **Nota didattica:** l'Orchestrator ha corretto se stesso sul campo `vcap_frames`.
> Thinking abilitato permette questo self-check prima di rispondere.
> Senza thinking, il modello avrebbe risposto immediatamente rischiando errori.

**Output plan_task (JSON risultante):**

```json
{
  "approach": "Simulazione fisica in loop principale con millis(), aggiornamento
               posizioni, rilevamento collisioni bordi e tra palline (elastiche,
               masse uguali), redraw display completo ogni frame",
  "libraries_needed": ["Adafruit_SSD1306", "Adafruit_GFX_Library"],
  "key_points": [
    "Wire.begin(21, 22) in setup",
    "display.begin(SSD1306_SWITCHCAPVCC, 0x3C)",
    "struct Ball { float x, y, vx, vy; int id, bounceCount; }",
    "3 istanze con posizioni/velocità iniziali diverse",
    "checkBoundaries(): rimbalzo su bordi, Serial WALL_N M",
    "checkCollisions(): distanza centri <= 6px → scambio velocità su normale",
    "drawAll(): clearDisplay + fillCircle x3 + display()"
  ],
  "note_tecniche": [
    "SDA=GPIO21 SCL=GPIO22",
    "I2C addr=0x3C",
    "raggio=3px, collision_dist=6px",
    "display 128x64, (0,0) top-left",
    "millis() no delay()",
    "baud 115200"
  ],
  "vcap_frames": 0,
  "vcap_interval_ms": 1000
}
```

---

## STEP 3 — plan_functions (in costruzione)

> *Questo step verrà aggiunto quando MI50 lo completa.*

---

## STEP 4 — generate_globals con M40 (in costruzione)

> *Questo step verrà aggiunto quando M40 genera la sezione globals.*

---

## STEP 5 — generate_all_functions con M40 (in costruzione)

> *Qui vedremo M40 implementare la fisica delle collisioni elastiche in C++.*

---

## STEP 6 — Compilazione con arduino-cli (in costruzione)

> *Vedremo eventuali errori e come il sistema li corregge.*

---

## STEP 7 — Upload su ESP32 e output seriale (in costruzione)

---

## STEP 8 — Valutazione visiva con MI50 Vision (in costruzione)

---

## Concetti fisici — collisione elastica tra cerchi

Per chi studia: quando due palline di uguale massa si scontrano, la fisica dice:

**Rilevamento collisione:**
```
distanza = sqrt((x2-x1)² + (y2-y1)²)
collisione = distanza <= r1 + r2  (= 6px per raggio=3)
```

**Normale della collisione** (vettore unitario dal centro A verso centro B):
```
nx = (x2 - x1) / distanza
ny = (y2 - y1) / distanza
```

**Scambio velocità su normale (masse uguali):**
```
// Componente della velocità relativa lungo la normale
dvx = vx2 - vx1
dvy = vy2 - vy1
impulso = dvx*nx + dvy*ny

// Solo se le palline si stanno avvicinando (impulso < 0)
if (impulso < 0):
    vx1 += impulso * nx
    vy1 += impulso * ny
    vx2 -= impulso * nx
    vy2 -= impulso * ny
```

> Questo è il codice che M40 dovrà produrre nella funzione `checkCollisions()`.
> Vedremo se lo genera correttamente al primo tentativo o se serve un ciclo di patch.

---

*Documento aggiornato durante la run — ultima modifica: 2026-03-19*
