# Boids con Predatore — Comportamento Emergente di Caccia e Fuga
> Data: 2026-03-21 (sessione pomeriggio)
> Run dir: `logs/runs/20260321_162709_Simulazione_Boids_con_Predatore_su_displ`
> Risultato: 🔄 IN CORSO

---

## Perché questo task è interessante

### La progressione evolutiva

```
pallina singola
  → tre palline (fisica multi-corpo)
    → muretto (collisioni AABB, game state)
      → muretto + attrattore (forza esterna, dinamica non-lineare)
        → BOIDS (forze inter-agente, comportamento emergente)
          → BOIDS + PREDATORE (steering behaviors, predator-prey dynamics)
```

I Boids puri (sessione precedente) dimostravano **ordine emergente senza controllo centrale**:
nessuna forza esterna, solo interazione locale tra vicini. Ogni agente seguiva 3 regole semplici
e lo stormo emergeva.

Il Predatore aggiunge una **asimmetria radicale**: due classi di agenti con obiettivi opposti.
Non è più un sistema omogeneo — è un ecosistema predatore-preda con dinamica evolutiva.

### Craig Reynolds e i Steering Behaviors (1987)

Dopo i Boids (1986), Reynolds sviluppò i **Steering Behaviors**: comportamenti autonomi per
agenti mobili. I più fondamentali:

- **Seek**: muoviti verso un target (il predatore cerca le prede)
- **Flee**: allontanati da una minaccia entro un raggio (le prede fuggono dal predatore)

Questi due comportamenti, combinati con i Boids standard, producono dinamiche di predazione
sorprendentemente realistiche:

- **Stormo compatto** quando il predatore è lontano (coesione vince)
- **Esplosione di fuga** quando il predatore si avvicina (flee vince sulla coesione)
- **Riformazione** dello stormo dopo che il predatore si allontana
- **CATCH**: momenti in cui il predatore raggiunge una preda (dist < 4px)

### Perché è un salto concettuale rispetto ai Boids puri

| Aspetto | Boids puri | Boids + Predatore |
|---------|-----------|-------------------|
| Agenti | Omogenei (8 boid) | Eterogenei (8 prede + 1 predatore) |
| Forze | Simmetriche | Asimmetriche (seek ≠ flee) |
| Dinamica | Ordine emergente | Competizione emergente |
| Output seriale | CLUSTER:n | HUNT:id DIST:px FLEE:n CATCH:id |
| Comportamento | Stormo stazionario | Caccia e fuga continua |

---

## Specifica tecnica

### Hardware
- Board: ESP32 NodeMCU (`esp32:esp32:esp32`)
- Display: OLED SSD1306 128×64, I2C SDA=21 SCL=22, addr=0x3C
- Seriale: 115200 baud

### Parametri fisici

| Parametro | Valore | Motivazione |
|-----------|--------|-------------|
| N prede | 8 | stesso dei Boids puri, confronto diretto |
| RADIUS | 25px | campo visivo prede |
| SEP_RADIUS | 8px | distanza minima sicura tra prede |
| FLEE_RADIUS | 30px | raggio di percezione del predatore |
| sep weight | 1.5 | evita accatastamenti |
| ali weight | 0.8 | coerenza direzionale |
| coh weight | 0.6 | tiene unito lo stormo |
| flee weight | 1.0 (×3 nella formula) | fuga forte ma non infinita |
| MAX_SPEED_PREY | 2.5 px/frame | prede veloci ma catturabili |
| MAX_SPEED_PRED | 2.0 px/frame | predatore più lento → caccia richiede strategia |
| MIN_SPEED | 0.5 px/frame | nessuno si ferma mai |
| seek strength | 0.4 px/frame² | accelerazione predatore verso preda |
| CATCH threshold | 4px | distanza = cattura |
| Delay loop | 30ms | ~33 fps |

**Nota sul bilanciamento**: MAX_SPEED_PREY > MAX_SPEED_PRED è fondamentale.
Se il predatore fosse più veloce delle prede, le catturerebbe sempre → nessuna dinamica.
Con questa asimmetria le prede possono sfuggire ma devono cooperare (flee + stormo).

### Rappresentazione visiva

- **Prede**: `drawPixel()` — 8 punti singoli (identici ai Boids puri)
- **Predatore**: croce 5 pixel (centro + 4 direzioni) — visivamente distinto dallo stormo

### Struttura funzioni

```
struct Boid { float x, y, vx, vy; bool isPredator; };
Boid boids[9];  // 0..7 = prede, 8 = predatore
int huntTarget = 0;  // preda attualmente inseguita

setup()           — init Wire, display, boids (cerchio iniziale), Serial
loop()            — updatePrey(); updatePredator(); updateDisplay(); printStatus(); delay(30)
initBoids()       — prede su cerchio r=20 attorno al centro; predatore angolo top-left
dist_boids(i,j)   — sqrt((xi-xj)²+(yi-yj)²)
separation(i)     — forza repulsiva 1/d² da vicini < SEP_RADIUS
alignment(i)      — vel media dei vicini < RADIUS
cohesion(i)       — vettore verso centro di massa dei vicini < RADIUS
flee(i)           — forza di fuga da predatore se dist < FLEE_RADIUS
updatePrey()      — sep*1.5 + ali*0.8 + coh*0.6 + flee; clamp; move; bordi abs()
updatePredator()  — seek preda più vicina (huntTarget); seek strength 0.4; clamp; move; bordi
updateDisplay()   — clearDisplay; drawPixel prede; croce predatore; display()
printStatus()     — ogni 2s: HUNT:id DIST:px FLEE:n; se dist<4: CATCH:id
```

### Output seriale atteso

```
HUNT:3 DIST:45 FLEE:2    — insegue preda 3, a 45px, 2 prede in fuga
HUNT:3 DIST:38 FLEE:3    — si avvicina, più prede percepiscono la minaccia
CATCH:3                   — raggiunto! (dist < 4px)
HUNT:5 DIST:62 FLEE:1    — cambia target verso preda 5
```

**Indicatori di successo**:
- DIST decresce nel tempo → seek funziona
- FLEE > 0 → le prede percepiscono il predatore
- CATCH appare → predatore raggiunge le prede

---

## Il Task precedente: Boids puri

Come confronto, ecco i frame dei Boids puri (sessione precedente).

### Frame 0 — t=0s
![boids frame 0](../logs/runs/20260321_140451_Simulazione_Boids_stormo_emergente_su/frame_000_134006_62663_s0.jpg)

*Stormo in alto-sinistra, forma dispersa a "L"*

### Frame 1 — t=2s
![boids frame 1](../logs/runs/20260321_140451_Simulazione_Boids_stormo_emergente_su/frame_001_134009_02253_s1.jpg)

*Stormo migrato al centro, forma compatta verticale*

### Frame 2 — t=4s
![boids frame 2](../logs/runs/20260321_140451_Simulazione_Boids_stormo_emergente_su/frame_002_134011_37912_s2.jpg)

*Stormo in curva verticale, zona centro-destra*

**Differenza con il predatore**: nei Boids puri il comportamento è stazionario —
il gruppo mantiene coesione ma non c'è tensione dinamica. Con il predatore
ogni frame racconta una storia di caccia.

---

## Run — planning MI50

### Timeline

| Ora | Evento |
|-----|--------|
| 16:27 | Task lanciato |
| 16:29 | Step 1 — MI50 `plan_task` |
| 16:29 | KB LESSONS (5) iniettate — inc. lesson costruttore SSD1306 |
| 16:35 | `plan_task` completato (6 min) |
| 16:37 | Step 2 — MI50 `plan_functions` |
| 16:50 | `plan_functions` completato (13 min) — 12 funzioni |
| 16:50 | PHASE → GENERATING — M40 genera in parallelo |
| 16:53 | `generate_globals` → 21 righe (37 sec) |
| 16:53 | Step 4 — `generate_all_functions` — M40 in parallelo (12 funzioni) |
| ... | In corso... |

### Piano MI50 — `plan_task` result

MI50 ha pianificato correttamente la struttura generale e i punti chiave:

```
Simulazione Boids su OLED SSD1306 128x64 con ESP32.
Implementazione delle 3 regole Boids (separazione, allineamento, coesione)
+ fuga dal predatore.
Il predatore (indice 8) insegue la preda più vicina.
Disegno pixel bianco per prede e croce per predatore.
```

**Key points identificati da MI50**:
1. Inizializza Wire su pin 21/22
2. Inizializza display OLED 128x64 con addr 0x3C
3. Posiziona 8 prede su cerchio e 1 predatore in alto a sinistra
4. Calcola forze di separazione, allineamento, coesione per prede
5. Calcola forza di fuga per prede in raggio del predatore
6. Predatore cerca e insegue la preda più vicina
7. Disegna prede come pixel e predatore come croce
8. Stampa stato su Serial ogni 2s

### Piano MI50 — `plan_functions` result (12 funzioni)

**Globals generati automaticamente**:

```cpp
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <math.h>
#define N_PREY 8
#define N_TOTAL 9
#define RADIUS 25.0f
#define SEP_RADIUS 8.0f
#define FLEE_RADIUS 30.0f
#define MAX_SPEED_PREY 2.5f
#define MIN_SPEED 0.5f
#define MAX_SPEED_PRED 3.2f
Adafruit_SSD1306 display(128, 64, &Wire, -1);
struct Boid { float x, y, vx, vy; bool isPredator; };
Boid boids[9];
unsigned long lastStatusPrint = 0;
int huntTarget = 0;
```

**Grafo delle dipendenze** (come pianificato da MI50):

```
dist_boids ←── separation ──┐
           ←── alignment  ──┤
           ←── cohesion   ──┼── updatePrey ──┐
           ←── flee       ──┘                 │
           ←── updatePredator ────────────────┤── loop
           ←── printStatus ──────────────────┤
initBoids                                     │
updateDisplay ───────────────────────────────┘
setup (chiama initBoids)
```

**Dettaglio 12 funzioni**:

| # | Funzione | Firma | Dipende da |
|---|----------|-------|-----------|
| 1 | `dist_boids` | `float dist_boids(int i, int j)` | — |
| 2 | `initBoids` | `void initBoids()` | — |
| 3 | `separation` | `void separation(int i, float &dx, float &dy)` | dist_boids |
| 4 | `alignment` | `void alignment(int i, float &dx, float &dy)` | dist_boids |
| 5 | `cohesion` | `void cohesion(int i, float &dx, float &dy)` | dist_boids |
| 6 | `flee` | `void flee(int i, float &dx, float &dy)` | dist_boids |
| 7 | `updatePrey` | `void updatePrey()` | sep, ali, coh, flee, dist_boids |
| 8 | `updatePredator` | `void updatePredator()` | dist_boids |
| 9 | `updateDisplay` | `void updateDisplay()` | — |
| 10 | `printStatus` | `void printStatus()` | dist_boids |
| 11 | `setup` | `void setup()` | — |
| 12 | `loop` | `void loop()` | updatePrey, updatePredator, updateDisplay, printStatus |

**Osservazione**: rispetto ai Boids puri (10 funzioni), il predatore aggiunge `flee` e `updatePredator`. La funzione `dist_boids` è il nodo centrale — 5 funzioni dipendono da essa.

---

## Codice generato

> *Verrà inserito al completamento della run*

---

## Run — generazione e compilazione

> *Questa sezione verrà completata al termine della run*

---

## Frame webcam

> *Frame inseriti al completamento della run*

---

## Analisi

> *Analisi inserita al completamento della run*

---

## Confronto con i Boids puri

| Aspetto | Boids puri | Boids + Predatore |
|---------|-----------|-------------------|
| Errori compilazione | 0 | ? |
| Patch necessarie | 0 | ? |
| Intervento manuale | 0 | ? |
| Autonomia totale | 100% | ? |

---

## Prossimi esperimenti naturali

1. **Predatore v2**: dopo CATCH la preda "muore" e viene rigenerata in posizione casuale
2. **Multi-predatore**: 2 predatori che cacciano cooperando (boids + seek per i predatori)
3. **Ostacoli**: mattoncini fissi che sia prede che predatori devono evitare
4. **Conway's Game of Life**: cambio radicale di paradigma — automa cellulare, zero fisica

---

> *Documento in aggiornamento durante la run*
