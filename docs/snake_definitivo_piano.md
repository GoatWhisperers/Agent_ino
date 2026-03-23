# Snake Definitivo — Piano di Progetto

> Autore: Claude (ruolo: utente/supervisore)
> Programmatore: MI50 (reasoning) + M40 (codice)
> Data: 2026-03-22 notte
> Hardware: ESP32 + OLED SSD1306 128×64

---

## Obiettivo

Costruire step by step un gioco Snake su ESP32+OLED che:
1. Si muove in modo intelligente (look-ahead, non casuale)
2. Impara di generazione in generazione (peso evolutivo)
3. (Bonus) Evita ostacoli fissi
4. (Bonus) Due serpenti in competizione

---

## Architettura tecnica — Step 1 (Snake Pulito)

### Struttura dati
```cpp
#define MAX_LEN 60
#define CELL 2          // dimensione pixel per segmento (2×2)
#define SCREEN_W 128
#define SCREEN_H 64
#define GRID_W (SCREEN_W / CELL)  // 64 celle
#define GRID_H (SCREEN_H / CELL)  // 32 celle

int pos[MAX_LEN][2];    // pos[0] = testa SEMPRE (shift body)
int length = 5;
int dir = 0;            // 0=R 1=D 2=L 3=U
int foodX, foodY;
int score = 0;
int frameDelay = 200;   // ms per frame, scende con score
bool alive = true;
```

**Nota critica**: corpo shiftato ad ogni frame (pos[i] ← pos[i-1]), NO circular buffer.
Il circular buffer ha causato GAMEOVER immediato nel L6.

### Funzioni richieste
```
setup()           → init display, seriale, serpente, cibo
loop()            → chooseDir + updateSnake + drawGame + delay
chooseDir()       → look-ahead 1 step: safe + vicino a cibo
isSafe(nx, ny)    → non muro, non corpo
updateSnake()     → shift corpo, muovi testa, check eat/gameover
randomFreePos()   → for(i<100): casuale non sovrapposto a corpo
drawGame()        → clearDisplay + disegna corpo + cibo + score + display()
resetGame()       → reinizializza tutto, generation++
```

### chooseDir() — logica esatta
```
dxTab[] = {1,0,-1,0}  // R D L U
dyTab[] = {0,1,0,-1}

oposto = (dir+2)%4  → escludi inversione 180°

per ogni d in [0..3] se d != oposto:
    nx = pos[0][0] + dxTab[d]
    ny = pos[0][1] + dyTab[d]
    se isSafe(nx, ny):
        safe_dirs.add(d)

se safe_dirs vuoto → qualsiasi dir (morte inevitabile, non bloccare)
altrimenti:
    scegli d in safe_dirs con min(abs(nx-foodX)+abs(ny-foodY))
```

### Serial events
```
"EAT"          → ogni volta che mangia
"SCORE:N"      → dopo ogni EAT
"GAMEOVER"     → collisione
"RESET"        → dopo game over screen, prima del restart
```

### Display
- Score nell'angolo in alto a sinistra (setTextSize 1)
- Corpo: fillRect(pos[i][0]*CELL, pos[i][1]*CELL, CELL, CELL, SSD1306_WHITE)
- Cibo: fillRect(foodX*CELL, foodY*CELL, CELL, CELL, SSD1306_WHITE)
- Game Over: "GAME OVER" centrato + score + attesa 2s + reset

---

## Architettura tecnica — Step 2 (Apprendimento)

### Parametro evolutivo
```cpp
int generation = 0;
int bestScore = 0;
float safetyBias = 0.5;  // 0=solo cibo, 1=solo sicurezza
```

### Modifica a chooseDir()
```
score per ogni safe_dir d:
    manhattan = abs(nx-foodX) + abs(ny-foodY)
    lookahead = contaViciniSafe(nx, ny)  // quante celle libere intorno
    score(d) = safetyBias * lookahead - (1-safetyBias) * manhattan

scegli d con score(d) massimo
```

### Evoluzione dopo ogni morte
```
generation++
se score > bestScore:
    bestScore = score
    safetyBias = min(0.9, safetyBias + 0.05)  // più prudente
altrimenti se score == 0 && generation > 3:
    safetyBias = max(0.1, safetyBias - 0.02)  // meno prudente

Serial.print("GEN:"); Serial.print(generation);
Serial.print(" SCORE:"); Serial.print(score);
Serial.print(" BEST:"); Serial.println(bestScore);
```

### Display aggiornato
- Riga 0: "S:N B:N"  (score attuale e best)
- Riga 1: "G:N"       (generation)

---

## Architettura tecnica — Step 3 (Ostacoli)

### Struttura
```cpp
#define N_OBSTACLES 4
int obstacles[N_OBSTACLES][4];  // {x,y,w,h} in celle
```

Ostacoli hardcoded a setup():
```
{10,8,2,6}, {20,4,6,2}, {40,20,2,6}, {50,8,6,2}
```

### Modifica a isSafe()
```
aggiungere check: (nx,ny) non dentro nessun ostacolo
```

### Display
- drawObstacle: fillRect per ogni ostacolo, stesso bianco del corpo

---

## Architettura tecnica — Step 4 (Due Serpenti)

### Struttura
```cpp
// Snake 1 (AI look-ahead + evolutivo)
int pos1[MAX_LEN][2]; int len1, dir1, score1;
// Snake 2 (AI più aggressiva: insegue il cibo ignorando il serpente 1)
int pos2[MAX_LEN][2]; int len2, dir2, score2;
// Cibo condiviso
int foodX, foodY;
```

### isSafe per snake1: evita muri + corpo1 + corpo2
### isSafe per snake2: evita muri + corpo2 (ignora corpo1 — aggressivo)

### Game over individuale: chi muore si resetta, l'altro continua
### Score display: "S1:N S2:N" in alto

---

## Anti-pattern M40 da specificare in ogni task

(Basati sulle lesson KB dalla sessione L1-L6)

1. **NO circular buffer** — pos[0] è sempre la testa, shift body ogni frame
2. **NO while(true) in randomFreePos** — SEMPRE `for(int i=0;i<100;i++)`
3. **NO SSD1306_RED/GREEN** — solo SSD1306_WHITE e SSD1306_BLACK
4. **NO display.display() multipli per frame** — UNO solo alla fine di drawGame()
5. **NO frameCount++ in due funzioni diverse** — un solo contatore
6. **NO int per millis()** — SEMPRE `unsigned long`
7. **NO textWidth()** — usare `getTextBounds()`
8. **Costruttore**: `Adafruit_SSD1306 display(128, 64, &Wire, -1)`
9. **begin**: `display.begin(SSD1306_SWITCHCAPVCC, 0x3C)`
10. **include obbligatori**: `Wire.h`, `Adafruit_GFX.h`, `Adafruit_SSD1306.h`

---

## Log sessione

Aggiornato in tempo reale durante la notte.
Vedere: `docs/snake_definitivo_sessione.md`

---

## Valutazione programmatore

Vedere: `docs/snake_definitivo_valutazione.md` (compilata a fine sessione)
