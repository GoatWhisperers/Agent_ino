# Visione del Sistema — Programmatore di Arduini

> Scritta il 2026-03-22, dopo Conway v3 e 82 lessons in KB.

---

## Cosa è il sistema

Un **programmatore autonomo per microcontrollori** con loop completo:

```
genera codice → compila → carica sull'hardware fisico → valuta → impara dai bug
```

Il dominio delle task è scelto dall'utente. Le task fin qui sono state fisica e simulazioni, ma questo è un limite dei task scelti — non del sistema.

---

## Perché le task tendono verso fisica e simulazioni

Organicamente, le simulazioni fisiche su OLED sono emerse come il caso di test ideale perché hanno tre proprietà rare in combinazione:

**1. Verificabilità visiva**
Il display mostra direttamente se qualcosa si muove, se gli agenti interagiscono, se l'automa evolve. La webcam + pipeline PIL/M40-vision/MI50-vision chiude il loop senza intervento umano.

**2. Verificabilità seriale**
`HIT`, `CATCH`, `GEN:`, `ALIVE:` sono eventi discreti e non ambigui. Il serial-first fast-path funziona perfettamente: se l'evento atteso è nel serial, la run è riuscita in 0.1 secondi senza analisi visiva.

**3. Bug ricchi e strutturati**
Boids, rimbalzi, automi cellulari producono bug specifici e ripetibili: predator.id OOB, swap doppio, serial spam, uint8_t* invece di uint8_t[][16]. Ogni bug diventa una lesson nella KB. Le lessons diventano valore reale per le run successive.

Un task come "accendi un LED ogni 500ms" è troppo semplice per far crescere il sistema. Un task come "simula Conway su OLED bit-packed" è abbastanza complesso da stressare ogni layer della pipeline e da produrre apprendimento genuino.

---

## Dove potrebbe andare

Il sistema non è un simulatore fisico — è un agente programmatore che ha scelto le simulazioni come campo di addestramento naturale. I percorsi possibili sono molto diversi:

| Direzione | Cosa succederebbe |
|-----------|-------------------|
| **Continua su fisica/grafica** | Diventa un sandbox di fisica 2D su microcontroller — KB ricca, M40 sempre più preciso su questo dominio specifico |
| **Giochi interattivi** | Joystick + OLED → Snake, Tetris, Pong — la fisica diventa game logic |
| **Sensori + attuatori** | Task IoT: temperatura, relay, MQTT — richiede un verificatore diverso (non visivo) |
| **Generalista** | Qualsiasi task Arduino/ESP32 — le lessons si stratificano per dominio, il sistema diventa uno strumento generico |

---

## La cosa più importante che sta succedendo

Il sistema non sta solo imparando a programmare Arduino.

Sta costruendo una **memoria tecnica strutturata** di pattern hardware+software su cui ragiona un LLM. Ogni run produce lessons. Ogni lesson viene recuperata semanticamente nelle run successive e iniettata nel contesto del modello, funzione per funzione.

Questo meccanismo è abbastanza generale:

```
qualsiasi dominio ripetitivo e verificabile
    → KB che cresce per pattern specifici del dominio
    → serial/sensor/visual evaluation adattata al dominio
    → M40 che genera con lessons iniettate per singola funzione
    → il sistema migliora senza fine-tuning
```

Elettronica, robotica, embedded Linux, firmware industriale — qualsiasi dominio con queste proprietà (ripetitivo, verificabile, bug strutturati) beneficerebbe della stessa architettura.

---

## La domanda giusta

Non "verso cosa sta evolvendo il sistema?" ma:

> **Cosa vuoi fare con l'ESP32 che ti interessa davvero?**

Il sistema si addestra su quello. Le lessons si accumulano su quello. M40 diventa preciso su quello.

La direzione la sceglie il task.

---

## Metriche attuali (2026-03-22)

| Metrica | Valore |
|---------|--------|
| Lessons in KB | 82 |
| Snippets in KB | 60+ |
| Fix proattivi in compiler.py | 9 funzioni |
| Regole in SYSTEM_FUNCTION (generator.py) | ~20 |
| Task completati con successo | muretto, boids puri, predatore v1, Conway v3 |
| Task parziali (success, done:false da bug pipeline) | predatore v2/v3, Conway v1/v2 |
| Patch medie per task (ultimi 5) | ~1.4 |

**Trend**: il numero di patch per task si riduce da run a run sullo stesso dominio. Conway v1: ~5 bug M40. Conway v3: 2 bug diversi, nessuno dei precedenti si è ripresentato. Le lessons funzionano.
