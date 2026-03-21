# Lezione: Gioco OLED con Attrattore Gravitazionale
> Data: 2026-03-21 (sessione pomeriggio)
> Run dir: `logs/runs/20260321_110158_Gioco_OLED_SSD1306_128x64_su_ESP32_3_pa`
> Risultato: ✅ SUCCESSO

---

## Il task

Gioco OLED su ESP32 con tre palline rimbalzanti che distruggono 6 mattoncini (2×3),
più un **puntino attrattore mobile** che esercita una forza gravitazionale sulle palline.

- Ogni mattoncino resiste 10 colpi poi sparisce
- Quando tutti distrutti: rigenerazione Fisher-Yates random
- Serial: `HIT` (ogni distruzione), `BREAK` (tutti distrutti), `REGEN` (rigenerazione)
- Attrattore: si muove rimbalzando sui bordi, attira le palline con forza `dx/dist * 0.06`

Il task è stato lanciato con descrizione **completamente upfront** (struttura funzione per funzione,
pseudocodice per ogni algoritmo, specifiche fisiche esatte). Strategia consolidata dalle run precedenti.

---

## Timeline

| Ora | Evento |
|-----|--------|
| 11:01 | Start run |
| 11:03 | `plan_task` → MI50 pianifica correttamente al primo colpo |
| 11:10 | `plan_functions` → 11 funzioni definite |
| 11:29 | `generate_globals` + `generate_all_functions` → 223 righe |
| 11:36 | `compile #1` → 8 errori (READY/REGEN/BREAK/HIT non dichiarati, attrVX const) |
| 11:42 | `patch_code v2` → M40 patcha ma produce backtick + 26 errori |
| 11:47 | `patch_code v3` → 179 righe, 0 errori locali |
| 11:52 | `upload_and_read` → **FAIL** "Compilazione pio fallita sul Raspberry" |
| ~12:00 | **SERVER CRASH** — sessione interrotta |
| 13:02 | **RESUME** da step 11 |
| 13:05 | `upload_and_read` → **OK**, 334 righe seriali di HIT |
| 13:09 | `grab_frames` → 3 frame catturati |
| 13:14 | `evaluate_visual` → `success=True` (opencv+M40) |
| 13:15 | `save_to_kb` |

---

## Intervento umano necessario

**Livello: medio-basso.** Un singolo intervento tecnico manuale, zero interventi sulla logica del task.

### Causa del blocco: `loop()` eliminata da M40 durante patch

Il bug critico che ha bloccato l'upload era: M40, durante il **secondo patch** (v3), ha
eliminato la funzione `loop()` dal codice. Il codice compilava con arduino-cli (che
probabilmente è più permissivo), ma il linker PlatformIO sul Pi lo rifiutava con:

```
undefined reference to 'loop()'
```

Questo è lo stesso comportamento già visto nella sessione muretto: **M40 durante il patch
tende a eliminare funzioni intere** quando riceve un messaggio d'errore confuso
(il secondo patch aveva backtick nel codice e M40 ha semplificato troppo).

**Fix applicato da Claude:**
1. Letto il codice v3 (179 righe)
2. Identificati tutti i bug logici (oltre a `loop()`)
3. Scritto `code_v4_manual_fix.ino` (210 righe) con tutti i fix
4. Verificato: arduino-cli OK + PIO sul Pi OK
5. Aggiornato `checkpoint.json` con il nuovo codice + phase=compiling
6. Lanciato `python agent/tool_agent.py --resume ...`

Da quel momento: **100% autonomo** fino a `save_to_kb`.

---

## Bug logici trovati nel codice generato (non catturati da compilazione)

### Bug A — `loop()` mancante (CRITICO)
M40 ha eliminato la funzione `loop()` durante il secondo patch.
Compilazione arduino-cli: passava (strano). PlatformIO: undefined reference.

**Fix:** riscrivere `loop()` esplicitamente.
**Lesson:** dopo ogni patch, verificare che `setup()` e `loop()` esistano ancora nel codice.

### Bug B — Forza attrattore assente in `updatePhysics()`
Il codice generato da M40 non ha implementato la forza gravitazionale verso l'attrattore
nonostante la specifica fosse dettagliatissima (formula esatta, pseudocodice).
M40 ha sì generato la struct `Attractor` e la variabile `attr`, ma non ha collegato
il calcolo della forza nel loop fisico.

**Fix:**
```cpp
float dx = attr.x - balls[i].x;
float dy = attr.y - balls[i].y;
float dist = sqrt(dx*dx + dy*dy);
if (dist > 5.0) {
  balls[i].vx += dx/dist * 0.06;
  balls[i].vy += dy/dist * 0.06;
}
// clamp max 3.0 px/frame
float spd = sqrt(balls[i].vx*balls[i].vx + balls[i].vy*balls[i].vy);
if (spd > 3.0) { balls[i].vx = balls[i].vx/spd*3.0; balls[i].vy = balls[i].vy/spd*3.0; }
```

### Bug C — Mattoncini distrutti al primo colpo invece che al 10°
`resolveBallBrickCollision()` non incrementava `hits`. Il codice faceva
`bricks[j].active = false` direttamente in `updatePhysics()` senza passare per hits.

**Fix:** togliere `bricks[j].active = false` da `updatePhysics()`, aggiungere in
`resolveBallBrickCollision()`:
```cpp
bricks[bri].hits++;
if (bricks[bri].hits >= 10) {
  bricks[bri].active = false;
  Serial.println(HIT_MSG);
}
checkAllDestroyed();
```

### Bug D — Collision detection AABB sbagliato
`updatePhysics()` usava `abs(x - brick.x) < BALL_R + BRICK_W` che controlla la distanza
tra centro-pallina e angolo-mattoncino invece di fare un vero AABB.
Casi con palline ai lati dei mattoncini davano falsi positivi.

**Fix AABB corretto:**
```cpp
if (balls[i].x + BALL_R > bricks[j].x &&
    balls[i].x - BALL_R < bricks[j].x + BRICK_W &&
    balls[i].y + BALL_R > bricks[j].y &&
    balls[i].y - BALL_R < bricks[j].y + BRICK_H)
```

### Bug E — Bordi senza abs()
`updatePhysics()` usava `vx = -vx` invece del pattern sicuro `abs()`.
Può causare palline incastrate se entrano troppo nel bordo.

**Fix:** pattern già consolidato:
```cpp
if (x < BALL_R)       { x = BALL_R;       vx =  abs(vx); }
if (x > 127 - BALL_R) { x = 127 - BALL_R; vx = -abs(vx); }
```

### Bug F — Velocità iniziale troppo bassa
`random(150)/100.0` produce 0.0–1.5 px/frame, spesso < 1.5.

**Fix:** `1.5 + (float)random(100)/100.0` → 1.5–2.5 px/frame garantita.

### Bug G — `regenOrder[]` non inizializzato
Fisher-Yates shuffle su `regenOrder` senza averlo prima riempito con `{0,1,2,3,4,5}`.

**Fix:** inizializzare in `initBricks()`: `regenOrder[i] = i;`

---

## Comportamento del sistema

### MI50 — ottimo
- Planning al primo colpo, 11 funzioni corrette, struttura rispettata
- Resume gestito autonomamente: ha capito il contesto dal checkpoint e ha chiamato
  `upload_and_read` senza confusione (nonostante la fase fosse "compiling" con 0 errori)
- `evaluate_visual` ha riconosciuto il gioco dall'analisi pixel senza vision model:
  blob_piccoli (palline), blob_medi (mattoncini), white_ratio elevato = display attivo

### M40 — problemi con patch multi-round
- Primo codice generato (223 righe): struttura corretta, bug logici multipli
- Patch 1: introduce backtick → 26 errori
- Patch 2: risolve backtick ma **elimina loop()** → PIO fallisce
- **Pattern critico**: ogni round di patch degrada il codice invece di migliorarlo
  quando il codice è già lungo e M40 fa refactoring implicito

### evaluate_visual — ottimo
- Serial-first: 334 righe di HIT = conferma funzionale immediata
- opencv+M40: blob detection ha riconosciuto palline + mattoncini senza MI50-vision
- Nessun falso negativo

---

## Score autonomia

| Fase | Autonomia | Note |
|------|-----------|------|
| Planning | 100% | MI50 al primo colpo |
| Code generation | ~60% | Bug logici multipli da fixare |
| Compilazione locale | 100% | 3 tentativi, 2 patch |
| Upload PIO | ❌ bloccato | loop() mancante — intervento manuale |
| Resume dopo fix | 100% | MI50 autonomo fino a fine |
| Valutazione | 100% | opencv+M40, serial-first |
| KB save | 100% | |

**Totale intervento**: 1 sessione di debug manuale (~30 min), 1 fix del codice (210 righe),
1 aggiornamento checkpoint, 1 resume. Tutto il resto autonomo.

---

## Novità rispetto alle run precedenti

1. **Task con attrattore gravitazionale** — prima volta con forza di attrazione dinamica.
   Funziona splendidamente: le palline vengono trascinate verso il punto mobile,
   creando traiettorie curvilinee visivamente interessanti.

2. **Resume dopo crash del server** — la sessione ha dimostrato che il sistema di
   checkpoint è robusto: il crash del server Claude a metà sessione non ha perso nulla.
   Il resume ha letto correttamente codice + fase + step e ha continuato senza perdita.

3. **Diagnosi del bug PIO** — per la prima volta abbiamo diagnosticato esplicitamente
   il problema "loop() mancante" correlato al comportamento di M40 nel multi-patch.
   Questo pattern va aggiunto come regola: **dopo ogni patch, controllare che setup() e loop() esistano**.

---

## Lessons da aggiungere in KB

1. **M40 patcher — loop() eliminata nel multi-round patch**
   - Verificare che setup() e loop() esistano dopo ogni patch
   - Se mancano: aggiungere esplicitamente nel codice (non in un patch ulteriore)

2. **Attrattore gravitazionale su OLED**
   - Pattern funzionante: `vx += (dx/dist)*0.06`, clamp max 3.0
   - L'attrattore deve muoversi con rimbalzo sui bordi (stessa formula abs())
   - La forza è abbastanza forte da curvare le traiettorie ma non da intrappolare le palline

3. **AABB collision detection corretto**
   - `ball.x + R > brick.x && ball.x - R < brick.x + W && ...` (4 check separati)
   - NON: `abs(ball.x - brick.x) < R + W` (falsi positivi ai bordi)

4. **Serial output come proxy funzionale**
   - 334 righe di HIT in 2 minuti = gioco attivo e collisioni funzionanti
   - Non serve valutazione visiva per confermare il funzionamento di base

---

## Conclusioni

Il sistema è diventato molto più capace rispetto alle prime sessioni. Con task description
completa upfront, MI50 pianifica correttamente al primo tentativo. Il codice generato
da M40 è quasi corretto: la struttura, gli include, le funzioni ausiliarie, la regen —
tutto giusto. I bug residui (attrattore mancante, hits, AABB) sono **bug logici sottili**
che richiedono comprensione del dominio per essere rilevati, non errori di sintassi.

Il prossimo passo naturale è: **M40 deve imparare a preservare setup() e loop() durante
i patch**. Questo è il bug sistemico più impattante rimasto aperto.
