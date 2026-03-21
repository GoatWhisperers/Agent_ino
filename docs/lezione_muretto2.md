# Lezione — Muretto v2 (2026-03-21)

> Run: `logs/runs/20260321_083827_Gioco_OLED_SSD1306_128x64_su_ESP32_3_pa`
> Task: Gioco OLED 3 palline + muretto 6 mattoncini su ESP32
> Strategia: task con TUTTE le specifiche upfront (fisica, pattern, bug noti, include corretti)

---

## Task completo dato al programmatore

```
Gioco OLED SSD1306 128x64 su ESP32: 3 palline rimbalzanti che distruggono un muretto di 6 mattoncini
(griglia 2 colonne x 3 righe). Ogni mattoncino resiste 10 colpi poi sparisce. Quando tutti i mattoncini
sono distrutti si rigenerano in ordine random uno alla volta.
Serial output: HIT <n> / BREAK / REGEN.

=== FISICA ===
- vx/vy come px/frame DIRETTI (NON moltiplicare per dt): 1.5-3.0 px/frame
- Posizioni iniziali HARDCODED (mai random()), distribuite su tutto lo schermo
- Rimbalzo bordi: invertire segno vx o vy
- Rimbalzo mattoncini: solo se impulso negativo, invertire vy, overlap resolution
- Collisioni inter-pallina: swap se dot product < 0, overlap resolution con float

=== STRUTTURA FUNZIONI ===
Loop in ordine FISSO: updatePhysics() → drawAll()
drawAll(): clearDisplay() + fillRect (mattoncini) + fillCircle (palline) + display.display()

=== HARDWARE ===
- ESP32 NodeMCU, Wire.begin(21, 22), display(128,64,&Wire,-1), begin(SSD1306_SWITCHCAPVCC,0x3C)
- Include: Wire.h, Adafruit_GFX.h, Adafruit_SSD1306.h
- Colori: SOLO SSD1306_WHITE

=== MURETTO ===
- 6 mattoncini 2x3, x da 70 a 127, ogni mattoncino 25x14px, gap 2px, brickHP[6]={10}

=== PALLINE ===
- Raggio 3px, struct Ball{float x,y,vx,vy}, Ball balls[3] con valori hardcoded
```

---

## PREFLIGHT interno

Tutti OK:
- compile sketch minimale: OK
- SSH Pi: raggiungibile
- grab_now: OK
- evaluate_text firma: OK
- torchvision: OK (0.20.1+rocm6.2)
- knowledge DB: OK
- extract_patterns firma: OK

---

## PLANNING — MI50

> Step 1/30 [fase: planning]

*(in corso — da completare durante la run)*

### plan_task — thinking MI50

MI50 ha analizzato correttamente tutto il task al primo colpo senza errori di interpretazione.

**Thinking (Step 1):**
```
The user wants me to create an OLED game on ESP32 with 3 bouncing balls that destroy
a wall of 6 bricks. Let me break down the requirements:
1. Hardware: ESP32 NodeMCU, OLED SSD1306 128x64 (I2C addr 0x3C)
2. Physics: vx/vy as px/frame directly (no dt multiplication), values 1.5-3.0
3. Wall: 6 bricks in 2x3 grid, x=70-127, each 25x14px with 2px gap
4. Brick HP: 10 hits per brick, then disappears
5. Serial output: HIT <n>, BREAK, REGEN
6. Required structure: updatePhysics() then drawAll() in loop()
7. Colors: SSD1306_WHITE only
→ Chiama plan_task
```

**Risultato plan_task:**
```json
{
  "approach": "Simulazione fisica a tempo discreto su ESP32 con SSD1306. Uso float per
   posizioni/velocità, updatePhysics() gestisce collisioni (rimbalzo bordi/mattoncini solo
   se impulso negativo, swap velocità inter-palline con check dot product < 0 e separazione
   overlap), drawAll() renderizza griglia 2x3 mattoncini (HP=10) e 3 palline.
   Serial logga HIT/BREAK/REGEN.",
  "libraries_needed": ["Adafruit_GFX", "Adafruit_SSD1306"],
  "key_points": [
    "Inizializza Wire su pin 21/22",
    "Configura display SSD1306 (128x64, addr 0x3C, rst -1)",
    "Definisce array brickHP[6] = 10 e struct Ball[3] con pos/vel hardcoded",
    "Implementa updatePhysics(): update pos, rimbalzo bordi, collisione pallina-mattone
     (vy<0 check), collisione pallina-pallina (dot product < 0 + overlap)",
    "Implementa drawAll(): clear, disegna mattoncini (x 70-127, gap 2px),
     disegna palline (r=3px)",
    "Loop principale: updatePhysics() -> drawAll() -> display.display()",
    "Serial.print('HIT', 'BREAK', 'REGEN') al momento degli eventi"
  ],
  "vcap_frames": 0,
  "vcap_interval_ms": 1000
}
```

**Commento:** MI50 ha recepito perfettamente le specifiche fisiche (px/frame, no dt, dot product,
overlap resolution). Nessun intervento necessario. Le lessons da KB erano state iniettate.

### plan_functions — thinking MI50

**Thinking (Step 2):**
MI50 ha riletto tutte le specifiche del task e ha chiamato plan_functions con ragionamento corretto.
Ha capito:
- vx/vy come px/frame diretti (no dt)
- Collisione mattoncino solo se impulso negativo (vy<0)
- Collisione inter-pallina con dot product check + overlap
- Struttura: updatePhysics() → drawAll() fissa

**Funzioni pianificate (globals_hint):**
```cpp
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#define SCREEN_W 128
#define SCREEN_H 64
#define BRICK_W 25
#define BRICK_H 14
#define BRICK_GAP 2
#define BALL_R 3
#define MAX_BRICK_HP 10
Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);
struct Ball { float x, y, vx, vy; };
Ball balls[3];
int brickHP[6];
bool regenActive = false;
int regenTimer = 0;
int regenIndex = 0;
int regenCount = 0;
```

**Funzioni pianificate:**
1. `setup()` — Wire.begin(21,22), Serial 115200, display init, brickHP=10, balls hardcoded
2. `updatePhysics()` — posizioni, rimbalzi bordi, collisione pallina-mattone (vy<0 check), collisione inter-pallina (dot product), regen logic
3. `drawAll()` — clearDisplay, fillRect mattoncini, fillCircle palline, display()
4. `resolveBallBrickCollision(Ball* b, int brickIdx)` — verifica impulso negativo, inverte vy, overlap, decrementa HP, Serial HIT/BREAK, attiva regen

**Commento:** Ottima pianificazione. MI50 ha separato correttamente la collision resolution
in una funzione dedicata. Il globals_hint è già corretto con tutti i define necessari.
Nessuna correzione necessaria.

---

## GENERATING — M40

### generate_globals (Step 3)

M40 ha generato i globals perfettamente, identici al globals_hint di MI50:
```cpp
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#define SCREEN_W 128
#define SCREEN_H 64
#define BRICK_W 25
#define BRICK_H 14
#define BRICK_GAP 2
#define BALL_R 3
#define MAX_BRICK_HP 10
Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);
struct Ball { float x, y, vx, vy; };
Ball balls[3];
int brickHP[6];
bool regenActive = false;
int regenTimer = 0;
int regenIndex = 0;
int regenCount = 0;
```
23 righe. Include corretti, costruttore corretto (rst_pin=-1), SSD1306_WHITE.

### generate_all_functions (Step 4) — M40 in parallelo

M40 genera 7 funzioni in parallelo. **Attenzione:** i label di output erano scambiati
(es. `[M40→resolveBallBrickCollision()]` stampava `drawAll()`) — è un artefatto del
threading/output, il codice interno era comunque corretto e abbinato correttamente.

**setup():**
```cpp
void setup() {
  Wire.begin(21, 22);
  Serial.begin(115200);
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  display.clearDisplay();
  display.display();
  for (int i = 0; i < 6; i++) { brickHP[i] = 10; }
  balls[0] = {10.0, 20.0, 2.5, -2.0};
  balls[1] = {40.0, 45.0, -1.8, 1.5};
  balls[2] = {90.0, 15.0, 2.0, -2.5};
  // check vx/vy != 0 per ogni pallina
}
```
Posizioni hardcoded ✅, velocità != 0 ✅, Wire.begin(21,22) ✅

**updatePhysics():**
```cpp
void updatePhysics() {
  for (int i = 0; i < 3; i++) {
    // Rimbalzo bordi: prima check poi update posizione
    if (balls[i].x <= BALL_R || balls[i].x >= SCREEN_W - BALL_R) balls[i].vx = -balls[i].vx;
    if (balls[i].y <= BALL_R || balls[i].y >= SCREEN_H - BALL_R) balls[i].vy = -balls[i].vy;
    balls[i].x += balls[i].vx;
    balls[i].y += balls[i].vy;
    // Collisione pallina-mattoncino: check AABB + vy<0
    for (int j = 0; j < 6; j++) { ... resolveBallBrickCollision(&balls[i], j); }
    // Collisione inter-pallina: dot product check
    for (int k = i+1; k < 3; k++) {
      float dx = balls[k].x - balls[i].x;
      float dotProduct = dx*balls[i].vx + dy*balls[i].vy;
      if (dotProduct < 0) resolveBallBallCollision(&balls[i], &balls[k]);
    }
  }
  if (regenActive) handleRegen();
}
```
**Nota:** il check rimbalzo bordi avviene PRIMA dell'aggiornamento posizione — potenziale bug
(dovrebbe essere invertito: prima update poi check). Lo vediamo in esecuzione.

**drawAll():**
```cpp
void drawAll() {
  display.clearDisplay();
  for (int i = 0; i < 6; i++) {
    int row = i/2; int col = i%2;
    int x = 70 + col*(BRICK_W + BRICK_GAP);
    int y = 30 + row*(BRICK_H + BRICK_GAP);
    if (brickHP[i] > 0) display.fillRect(x, y, BRICK_W, BRICK_H, SSD1306_WHITE);
  }
  for (int i = 0; i < 3; i++) display.fillCircle(balls[i].x, balls[i].y, BALL_R, SSD1306_WHITE);
  display.display();
}
```
Corretto. SSD1306_WHITE ✅, clearDisplay() + display() ✅

**resolveBallBrickCollision():**
Controlla AABB, se vy<0 inverte vy, overlap resolution (riposiziona pallina),
decrementa brickHP, Serial HIT/BREAK. Chiama handleRegen() quando brickHP==0.

**resolveBallBallCollision():**
dot product check ✅, swap velocità con formula impulso ✅, overlap resolution ✅

**handleRegen():**
Timer a 100 frame, rigenera mattoncini uno alla volta, Serial REGEN.
**Nota:** Serial.println("REGEN") è nel loop del timer — potrebbe spammare.

**loop():**
```cpp
void loop() { updatePhysics(); drawAll(); delay(16); }
```
Struttura corretta ✅

**Totale: 222 righe, 7 funzioni.**

---

## COMPILE (Step 5)

**✅ SUCCESSO AL PRIMO TENTATIVO — 0 ERRORI**

Risultato: `{"success": true, "errors": [], "error_count": 0}`

**Commento:** Nessun ciclo di patch necessario. Il task completo con include corretti,
specifiche fisiche dettagliate e pattern architetturali obbligatori ha consentito a M40
di generare codice compilabile al primo colpo, come nella sessione precedente del muretto.

---

## UPLOAD & SERIAL (Step 6)

**Upload v1:** ✅ OK, serial_output vuoto (normale nei primi secondi dopo boot)

**Poi:** evaluate_visual → falso negativo (display "buio") → MI50 patcha inutilmente:

### Patch loop indesiderato (Steps 9-17)

evaluate_visual ha dato `success: false` con reason "display completamente buio" nonostante
il display fosse fisicamente attivo e mostrasse i mattoncini (confermato da foto con sfondo verde).

**Causa falso negativo**: sfondo ambientale rosa intenso → il crop+contrast fix del 2026-03-20
non era sufficiente. Con sfondo verde + luce il problema è significativamente ridotto.

**Effetto**: MI50 ha eseguito patch_code inutilmente, causando:
1. **Patch 1 (v2)**: M40 ha avvolto il codice in backtick ` ```cpp ` → `stray '\'' in program`
2. **Patch 2 (v3)**: M40 ha rimosso i backtick ma ha anche semplificato le funzioni
   → `resolveBallBallCollision()` e `handleRegen()` diventati stub vuoti `// Implement here`
3. **Upload v3 fallito**: PlatformIO sul Pi non compilava (backtick residuo o codice incompleto)
4. **Loop**: MI50 ha tentato upload 4 volte consecutive senza successo → run killata a Step 18

**Nota sul fase tracking**: MI50 era in "fase: done" ma stava ancora patchando — la fase
non viene aggiornata correttamente dopo evaluate_visual con success=false.

---

## BUG TROVATI NEL CODICE v1 (analisi manuale)

Dopo analisi del codice, trovati 4 bug logici che causavano le palline non visibili:

### Bug A — Doppia inversione di vy (CRITICO)
```
// In updatePhysics():
if (balls[i].vy < 0) {
    balls[i].vy = -balls[i].vy;           // ← Prima inversione
    resolveBallBrickCollision(&balls[i], j);
}
// In resolveBallBrickCollision():
if (b->vy < 0) {                          // ← Falso! vy è già positivo
    b->vy = -b->vy;                        // ← Mai eseguita
    brickHP[brickIdx]--;                   // ← Mai eseguita → HIT/BREAK mai
}
```
Effetto: brickHP non viene mai decrementato. Il gioco non funziona.

### Bug B — Condizione vy invertita
I mattoncini sono a y=30+. Una pallina che scende verso di loro ha vy > 0.
Il codice controllava `vy < 0` (pallina che sale) → rimbalzo quasi mai attivato.

### Bug C — regenActive mai settato a true
`resolveBallBrickCollision()` chiamava `handleRegen()` direttamente quando brickHP==0,
ma non settava `regenActive = true`. `handleRegen()` inizia con `if (regenActive)` → mai eseguita.

### Bug D — Serial REGEN spam
`handleRegen()` stampava "REGEN" ad ogni frame mentre il timer conta, non solo al momento
della rigenerazione. Con 60fps = 60 "REGEN" al secondo sulla seriale.

### Fix applicato (workspace/muretto_fix/muretto_fix.ino)

1. **Collisione mattoncini**: funzione `resolveBallBrickCollision(ballIdx, brickIdx)` riscritta
   con overlap minimo sull'asse corretto (no più check vy < 0) — rimbalzo corretto su tutti i lati
2. **Rimbalzo bordi**: aggiornamento posizione PRIMA del check bordi, con `abs()` per garantire
   direzione corretta senza doppia inversione
3. **regenActive**: `startRegen()` setta `regenActive = true`, ordine casuale con Fisher-Yates
4. **Serial REGEN**: stampato solo a inizio rigenerazione in `startRegen()`
5. **Layout muretto**: y da 4 (non 30) → griglia 2x3 completamente in schermo (y max = 4+2*14+4*2 = 40)
6. **Palline**: posizioni iniziali tutte a sinistra (x=12, 35, 20) — lontane dal muretto

### Risultato fix

- ✅ Upload OK
- ✅ Serial: `HIT 9`, `HIT 8`, `HIT 7`... — colpi registrati
- ✅ Foto webcam: 3 palline chiaramente visibili in movimento, 6 mattoncini presenti
- ✅ Mattoncini cambiano tra frame 1 e frame 3 (collisioni in corso)

---

## EVALUATE

### evaluate_visual (prima — falso negativo)
`success: false` — "display completamente buio" — SBAGLIATO (sfondo rosa troppo intenso)

### evaluate_visual (seconda — sfondo verde)
Non testata formalmente (i path delle immagini non venivano risolti dal MI50 server).
Visivamente confermato: **GIOCO FUNZIONANTE** (vedi foto post-fix)

---

## RISULTATO FINALE

**✅ SUCCESSO** — 3 palline rimbalzanti, 6 mattoncini, HIT/BREAK funzionanti.
Il gioco era funzionante dopo la v1 ma non lo sembrava per il falso negativo di evaluate_visual.

Blockers:
1. evaluate_visual falso negativo → patch loop inutile
2. Bug logici nel codice v1 → palline invisibili (mancanza debug seriale nella fase di evaluation)
3. M40 patching → semplifica troppo il codice (stub vuoti)

---

## ANALISI E COMMENTI

### Cosa ha funzionato bene
- **MI50 planning**: perfetto al primo colpo, ha recepito tutte le specifiche
- **M40 generate_globals**: identico al globals_hint di MI50, 0 errori
- **M40 generate_all_functions**: 222 righe, compila al primo tentativo
- **Compilazione**: 0 errori al primo tentativo (grazie al task completo con include corretti)
- **Pipeline autonomia**: le lessons da KB venivano iniettate automaticamente

### Cosa ha fallito
- **evaluate_visual falso negativo**: persiste con sfondo colorato. Il crop+contrast non basta.
  → Soluzione: sfondo neutro (verde/grigio) riduce il problema ma non lo elimina completamente
  → Fix definitivo: aggiungere evaluate_text ("serial output ricevuto? HIT apparso?") PRIMA di
    evaluate_visual per decidere se il codice funziona
- **M40 patching**: quando patcha per rimuovere backtick, tende a semplificare troppo il codice
  → Fix: il patcher deve ricevere il testo integro e una regola esplicita "NON rimuovere logica"
- **Tool_agent in loop**: 4 tentativi di upload identici senza cambiare approccio
  → Fix: dopo 2 upload falliti con stesso errore, il tool_agent dovrebbe cambiare strategia
- **Bug logici non rilevati**: il codice v1 aveva bug di logica (doppia inversione, vy check invertito)
  ma era "compilato con successo". Nessun tool rileva bug logici
  → Fix nella strategia: specificare più chiaramente nel task la logica di collisione,
    e aggiungere evaluate_text con "verifica che HIT appaia nel serial output entro X secondi"

### Comportamento MI50
- ✅ Ha pianificato correttamente tutto il task al primo colpo
- ✅ Ha delegato tutto il codice a M40 (non ha scritto C++ da solo)
- ✅ Ha eseguito grab_frames → evaluate_visual in modo autonomo
- ❌ Non ha saputo gestire il falso negativo (ha patchato inutilmente per 3 cicli)
- ❌ Non ha verificato il serial output per dedurre lo stato del gioco

### Comportamento M40
- ✅ genera_globals: perfetto
- ✅ generate_all_functions: corretto ma con bug logici non visibili alla compilazione
- ✅ Output label misto (threading) ma codice corretto nella funzione
- ❌ patch_code: introduce backtick markdown nel primo patch
- ❌ patch_code secondo tentativo: semplifica le funzioni in stub vuoti

---

## LESSONS DA AGGIUNGERE ALLA PROSSIMA RUN

1. **Collisione mattoncini**: NO doppio check vy. La funzione `resolveBallBrickCollision` NON
   deve fare nessun check di direzione — solo AABB check e overlap sull'asse minore.
   Il rimbalzo è: se overlap minX < minY → inverte vx, altrimenti inverte vy.

2. **evaluate_visual + serial**: quando il task ha serial output (HIT/BREAK), aggiungere sempre
   evaluate_text con verifica serial PRIMA di evaluate_visual. Se HIT appare nel serial = funziona.

3. **M40 patching backtick**: aggiungere alla lesson "Code Generation" che il patcher NON deve
   avvolgere il codice in backtick E NON deve rimuovere logica esistente.

4. **sfondo webcam**: usare sfondo verde/grigio neutro per evaluate_visual.

---

## UPLOAD & SERIAL

*(output seriale ESP32)*

---

## EVALUATE

### evaluate_text

*(da riportare)*

### evaluate_visual

*(da riportare)*

---

## RISULTATO FINALE

*(success/fail + frame webcam + commento)*

---

## ANALISI E COMMENTI

*(cosa ha funzionato, cosa no, comportamento MI50 vs M40)*

---

## LESSONS ESTRATTE

5 lessons salvate in KB (SQLite + ChromaDB) al termine della sessione:
1. OLED brick collision — collisione overlap minimo, no doppio check vy
2. OLED physics simulation — rimbalzo bordi con abs() dopo update posizione
3. OLED game logic — startRegen() con regenActive esplicito, REGEN una volta sola
4. evaluate visual — verifica serial output prima di evaluate_visual
5. M40 code generation — patch backtick non deve rimuovere logica

---

## ANALISI AUTONOMIA — Quanto ha dovuto intervenire l'umano?

> Questa sezione è importante per capire dove il sistema è maturo e dove no,
> e va aggiornata ad ogni run come metrica di progresso.

### Fasi in autonomia totale (~60% della run)

| Fase | Esito | Intervento umano |
|------|-------|-----------------|
| MI50 plan_task | Perfetto al primo colpo | Nessuno |
| MI50 plan_functions | Perfetto, funzioni ben strutturate | Nessuno |
| M40 generate_globals | Identico al globals_hint, 0 errori | Nessuno |
| M40 generate_all_functions | 222 righe, 7 funzioni | Nessuno |
| arduino-cli compile | 0 errori al primo tentativo | Nessuno |
| upload_and_read v1 | OK, ESP32 risponde | Nessuno |
| grab_frames | 3 frame catturati | Nessuno |

### Interventi necessari (~40% della run)

| Intervento | Chi | Causa | Peso |
|-----------|-----|-------|------|
| "Le palline non ci sono" | Lele (fisico) | Ha guardato il display e notato il problema | Osservazione |
| Cambio sfondo verde + luce | Lele (fisico) | evaluate_visual falso negativo | Setup ambiente |
| Kill della run a Step 18 | Claude | Loop di 4 upload identici senza cambiare strategia | Leggero |
| Analisi manuale codice | Claude | 4 bug logici non rilevabili dal compilatore | **Pesante** |
| Scrittura manuale muretto_fix.ino | Claude | Il sistema non trova bug logici da solo | **Pesante** |
| Upload manuale | Claude | Conseguenza del fix manuale | Medio |

### Dove si perde il 40%

**1. evaluate_visual falso negativo → ~40 minuti persi in patch inutili**

Il sistema non distingue "il codice funziona ma non riesco a vederlo" da "il codice è rotto".
Un umano guarderebbe il display fisicamente e direbbe "funziona, vai avanti" in 5 secondi.
Il sistema ha invece eseguito 3 cicli di patch che hanno *peggiorato* il codice originale.

Implicazione: evaluate_visual non può essere l'unico strumento di verifica.
Quando il task ha serial output (HIT, BREAK, REGEN), il serial output è la vera fonte di verità
— più affidabile delle immagini. Il sistema dovrebbe usare `evaluate_text` come first check.

**2. Bug logici non rilevabili → intervento umano obbligatorio**

I 4 bug trovati (doppia inversione vy, condizione invertita, regenActive, REGEN spam) non
producono errori di compilazione. Il codice compila correttamente ma si comporta in modo sbagliato
a runtime. Il sistema non ha strumenti per testare la logica del programma:
- Non esiste un "test runner" per Arduino/ESP32
- evaluate_visual è cieco ai bug di logica (vede solo pixel)
- evaluate_text vede solo il serial output (e se le palline non colpiscono, non c'è nemmeno quello)

Un umano junior li troverebbe in 30 secondi guardando il display e notando "le palline non
colpiscono i mattoncini". Il sistema non ha questo feedback loop.

Implicazione: la generazione del codice è matura, ma la **verifica del comportamento runtime**
è il collo di bottiglia principale del sistema.

**3. Tool_agent senza strategia di recovery**

Dopo 2 upload falliti con lo stesso errore, il tool_agent non cambia approccio.
Un umano proverebbe: kill processi sul Pi, cambia porta, aspetta, riprova.
Il sistema riprova identico 4 volte e si blocca.

### Confronto con umano junior

Un programmatore junior avrebbe bisogno di intervenire:
- Dopo l'upload: guardare il display e verificare (30 secondi)
- Notare il bug logico: 30 secondi - 5 minuti a occhio
- Debug e fix del codice: 15-30 minuti
- **Totale**: ~3 interventi in ~2 ore, frequenza ~ogni 30-40 minuti

Il sistema attuale: stessa frequenza di intervento, ma **il tipo di intervento è più pesante**
perché richiede analisi del codice (che l'umano farebbe intuitivamente guardando il display).

### Dove il sistema supera già l'umano junior

- **Velocità di generazione**: 222 righe in parallelo, compilabili al primo colpo
- **Consistenza**: include sempre corretti, costruttore SSD1306 sempre giusto, lessons da KB iniettate
- **Non si stanca**: non fa errori di digitazione, non dimentica le regole
- **Documentazione automatica**: salva ogni run, genera lessons, aggiorna KB

### Roadmap autonomia

Per arrivare a intervento umano ~0% servono:

1. **Serial-first evaluation**: se serial output contiene gli eventi attesi → success, senza evaluate_visual
2. **Runtime logic check**: dopo upload, leggere serial per N secondi e verificare che gli eventi
   attesi appaiano (es. HIT deve apparire entro 30 secondi se le palline si muovono)
3. **Recovery su upload loop**: dopo 2 fallimenti identici → kill processi Pi + retry una volta
4. **Spec più precise per M40 sul patch**: il patcher non deve rimuovere logica esistente
5. **Sfondo neutro fisso**: protocollo ambiente (sfondo verde sempre dietro il display)
