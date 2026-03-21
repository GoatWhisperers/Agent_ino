# Ciao Tommaso — cosa stiamo facendo qui

> Versione: 2026-03-21

---

## Il progetto in una frase

Abbiamo costruito un sistema che **scrive codice per microcontrollori da solo**, lo carica
su hardware fisico, guarda cosa succede e impara dagli errori.

---

## L'hardware — cosa c'è sul tavolo

```
┌─────────────────────────────────────────────────────────┐
│  PC con due vecchie GPU da server:                      │
│   • MI50 (AMD, 32 GB) — "il cervello"                  │
│   • M40 (NVIDIA, 11.5 GB) — "le mani veloci"           │
└────────────────────┬────────────────────────────────────┘
                     │ SSH (rete locale)
                     ▼
┌─────────────────────────────────────────────────────────┐
│  Raspberry Pi 3B (€35)                                  │
│   • collegato via USB all'ESP32                         │
│   • collegato via CSI alla webcam                       │
└────────────┬────────────────┬───────────────────────────┘
             │                │
             ▼                ▼
      ESP32 (€3)         Webcam CSI (€8)
  microcontrollore       vede lo schermo
   con schermo OLED      e manda i frame
       da €5
```

**Totale hardware "target"**: circa 16 euro.
Le GPU da server le abbiamo prese usate — costano meno di una GPU gaming moderna.

---

## Il problema che risolviamo

Programmare un microcontrollore richiede:
1. Sapere quali librerie usare
2. Conoscere l'API esatta (spesso con bug di documentazione)
3. Compilare con un toolchain specifico
4. Caricare il binario via USB con il tool giusto
5. Leggere l'output seriale e capire se funziona
6. Vedere fisicamente lo schermo per valutare

Ogni passo ha insidie. Il nostro sistema fa **tutto questo in autonomia**.

---

## Come funziona — il loop

Dai un task in italiano:

> *"Simula uno stormo di uccelli sullo schermo OLED"*

Il sistema:

**1. Pianifica** (MI50, ~7 minuti)
> Capisce cosa serve: librerie OLED, struttura dati, 10 funzioni, dipendenze tra loro.
> Sa già dai task precedenti: "il costruttore SSD1306 vuole -1 come quarto parametro, non l'indirizzo I2C".

**2. Genera il codice** (M40, ~3 minuti, in parallelo)
> Scrive tutte le funzioni contemporaneamente — separation(), alignment(), cohesion(), ecc.
> 156 righe di C++ da zero.

**3. Compila** (arduino-cli, ~30 secondi)
> Se ci sono errori: MI50 li analizza, M40 patcha il codice. Max 3 tentativi.

**4. Carica sull'ESP32** (PlatformIO via SSH sul Raspberry, ~1 minuto)
> Il Raspberry fa il flash fisico tramite cavo USB.

**5. Guarda e valuta** (webcam + seriale)
> La webcam vede lo schermo OLED. Il seriale dice cosa sta succedendo.
> Il sistema decide se il task è riuscito.

**6. Impara** (MI50)
> Salva i pattern che hanno funzionato. La prossima volta sa già come farlo.

---

## Il momento magico — i Boids

Il 2026-03-21 abbiamo raggiunto il **100% di autonomia** per la prima volta.

Task: simulare i "Boids" — un algoritmo del 1986 di Craig Reynolds che simula gli stormi
con tre regole semplicissime:

```
1. Separazione  → stai lontano dai vicini troppo vicini
2. Allineamento → vai nella stessa direzione dei vicini
3. Coesione     → vai verso il centro del gruppo
```

Tre regole, nessun coordinamento centrale, e ne emergono comportamenti come
gli stormi di storni, i banchi di pesci, gli sciami di insetti.

**Il sistema ha generato 156 righe di C++, compilato al primo tentativo, caricato
sull'ESP32, valutato il risultato — zero intervento umano.**

Su uno schermo da €5, con un microcontrollore da €3, in 38 minuti.

---

## I Boids — le immagini

Ecco cosa vede la webcam sullo schermo OLED (128×64 pixel, monocromatico):

```
Frame 0 (t=0s):    Frame 1 (t=2s):    Frame 2 (t=4s):
  * *                  ***                 **
 *   *                 ***                ***
  * *                                     **

Stormo a "L"        Compatto al          Curva verticale
in alto-sinistra    centro               centro-destra
```

In 4 secondi lo stormo si è spostato di 60 pixel — il 47% dello schermo.
Ogni `*` è un boid. Sono 8 pixel su 8192 totali, eppure si muovono come un'entità unica.

---

## Ora stiamo facendo: il Predatore

Stesso scenario, ma aggiungiamo **un predatore**:

- Le 8 prede continuano a fare i Boids
- Il predatore insegue la preda più vicina (**Seek** behavior)
- Le prede fuggono quando il predatore si avvicina (**Flee** behavior)
- Quando si avvicina a meno di 4 pixel: **CATCH**

L'output seriale ogni 2 secondi:
```
HUNT:3 DIST:45 FLEE:2    ← insegue la preda 3, a 45px, 2 prede stanno fuggendo
HUNT:3 DIST:38 FLEE:3    ← si avvicina, più prede lo percepiscono
CATCH:3                   ← preso!
HUNT:5 DIST:62 FLEE:1    ← nuovo target
```

Questo si chiama **Steering Behavior** — inventato da Craig Reynolds nel 1987,
usato in Batman Returns (1992) per i pipistrelli e i pinguini.

Su un OLED da €5 e un ESP32 da €3.

---

## La progressione degli esperimenti

```
Giorno 1:  pallina singola che rimbalza
Giorno 2:  tre palline (fisica multi-corpo)
Giorno 3:  muretto breakout (collisioni AABB, game state)
Giorno 4:  attrattore gravitazionale (forza dinamica)
Giorno 5:  Boids — stormo emergente (100% autonomia!)
Giorno 6:  Boids + Predatore (oggi, in corso...)
```

Ogni task è stato anche un test del sistema stesso — quanto può fare da solo?
La risposta è migliorata ogni giorno.

---

## Cosa impara il sistema

Dopo ogni run riuscita, il sistema salva "lessons" nel database:

> "Il costruttore SSD1306 vuole -1 come reset pin, non l'indirizzo I2C.
>  Se metti l'indirizzo I2C il display si blocca silenziosamente."

> "Il pattern per i bordi è: if(x < R) { x = R; vx = abs(vx); }
>  L'abs() è fondamentale — senza, le palline possono incastrarsi nel bordo."

> "Dopo ogni patch verifica che setup() e loop() esistano ancora nel codice.
>  M40 tende a eliminarli quando risolve altri errori."

La prossima volta che generiamo codice OLED, queste lessons vengono automaticamente
iniettate nel contesto di MI50 — non sbaglia più gli stessi errori.

---

## Perché due GPU con ruoli diversi?

**MI50** (il cervello) — usa Qwen3.5-9B in bfloat16 completo:
- Pensa lentamente ma bene (5-15 min per risposta)
- Pianifica, ragiona sugli errori, valuta il risultato
- Ha 32 GB di VRAM — può tenere il modello completo

**M40** (le mani) — usa Qwen3.5-9B quantizzato Q5 (più piccolo del 40%):
- Genera veloce (~33 token/sec)
- Non ragiona — traduce pseudocodice in C++ preciso
- 11.5 GB di VRAM — il modello ci sta appena

Stessa architettura di modello (Qwen3.5-9B), ruoli completamente diversi.
Come un architetto e un muratore — stesso linguaggio, competenze complementari.

---

## I numeri

| | MI50 | M40 |
|--|------|-----|
| Modello | Qwen3.5-9B bfloat16 | Qwen3.5-9B Q5_K_M |
| VRAM | 32 GB (AMD) | 11.5 GB (NVIDIA) |
| Velocità | ~2 tok/sec | ~33 tok/sec |
| Tempo per risposta | 5-15 min | 30-90 sec |
| Ruolo | Cervello | Mani |
| Costo GPU (usata) | ~€300 | ~€200 |

**Totale sistema**: ~€500 in GPU + ~€50 in hardware Arduino/Raspberry.
Zero cloud, zero API key, zero abbonamenti.

---

## Prossimi passi

- **Conway's Game of Life** — automa cellulare, niente fisica, pura logica discreta
- **Multi-predatore cooperante** — 2 predatori che cacciano insieme
- **Boids con ostacoli** — mattoncini fissi che gli agenti devono evitare
- **Altri microcontrollori** — Arduino Uno, STM32, RP2040

---

*Il codice è su: `github.com/GoatWhisperers/Agent_ino`*
