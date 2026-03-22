# Lezione: Conway Game of Life v2 — 2026-03-22 notte (ore 02:42-03:39)

## Stato finale
- **Compilazione**: OK (compile #3 — dopo 2 patch)
- **Upload**: OK
- **Simulazione hardware**: ✅ FUNZIONANTE — display OLED mostra pixel bianchi, MI50-vision conferma
- **Valutazione**: evaluate_visual: success=True [mi50-vision-fallback]
- **Run end**: ❌ FAILED (MI50 in done phase ha detto success=false — bug pipeline senza eval_result in anchor_done)
- **result.json**: success=True

## Miglioramenti rispetto a v1
| v1 Bug | v2 Status |
|--------|-----------|
| Double swapGrids | ✅ FIXATO — swap solo in loop() |
| Bit packing errato (x%BITMAP_COLS) | ✅ FIXATO — usa helper getCell/setCell con x/8 |
| gridX sbagliato in computeNext | ✅ FIXATO — for(y) for(x) con getCell diretti |
| checkStability() bit order invertito | ✅ FIXATO — usa getCell |
| Serial spam ogni frame | ⚠️ ANCORA PRESENTE — 80142 righe/10s (causa ignota) |

## Bug M40 rimasti

### Bug 1: `uint8_t* grid` invece di `uint8_t grid[][16]`
**Causa**: M40 ha usato `uint8_t* grid` nelle firme di getCell/setCell/countNeighbors.
**Errore**: "cannot convert 'uint8_t (*)[16]' to 'uint8_t*'" (15 errori in compile #1).
**Fix applicato da M40 al compile #2**: M40 ha corretto autonomamente le firme.
**Fix sistemico aggiunto**: `_fix_uint8_grid_pointer()` in compiler.py (proattivo + error-triggered).

### Bug 2: Backtick in output M40
**Causa**: M40 ha aggiunto ``` ``` ``` fences nel codice patched.
**Errore**: "stray '`' in program" (26 errori in compile #2).
**Fix applicato da M40 al compile #3**: M40 ha rimosso i backtick.
**Fix sistemico**: già gestito da SYSTEM_PATCH con la regola BACKTICK.

### Bug 3: Serial spam persistente (causa non determinata)
**Sintomo**: 80142 righe in 10 secondi = 8014 righe/sec = 2671 prints/sec con SERIAL_INTERVAL=5000ms (dovrebbe essere 2 prints in 10s).
**handleSerialOutput()**: correttamente usa `millis() - lastSerialTime >= SERIAL_INTERVAL`.
**Causa sospetta**: la computazione + display potrebbe non avanzare correttamente, oppure `millis()` ha un comportamento imprevisto, oppure c'è un'altra print nascosta nel codice.
**Effetto**: serial output inutilizzabile per valutazione funzionale (nessun HIT pattern semplice da cercare).
**Fix necessario**: aggiungere `delay(16)` in loop() dopo drawGrid() — forza il frame rate a max ~60fps e garantisce che millis() avanzi.

### Bug 4: Nessuna gestione del caso "stable → reinit"
**Causa**: quando `isStable=true`, il codice stampa "Stable: 1" ma NON reinizializza la griglia.
**Effetto**: la simulazione si blocca in stato stabile per sempre (ma almeno non crasha).
**Fix necessario**: `if (isStable) { initGrid(); randomizeGrid(); }` in loop().

## Bug sistemici pipeline scoperti

### Bug: done phase senza eval_result → MI50 confuso da serial spam
**Causa**: il processo v2 è stato avviato PRIMA che le modifiche a `_anchor_done` (con eval_result) fossero committate.
**Effetto**: MI50 in done phase vede ultime 8 righe di serial (tutte "Stable: 0\n9...") e dice success=False.
**Fix**: le modifiche a `_anchor_done` sono già committate (commit 7453695) — valide per il prossimo run.

### Bug: proactive fix `_fix_uint8_grid_pointer` non disponibile al processo
**Causa**: il processo v2 è stato avviato PRIMA del commit con `_fix_uint8_grid_pointer`.
**Effetto**: compile #2 ha usato fix_known_api_errors che non aveva il pattern `cannot convert 'uint8_t (*)[16]'`.
**Fix**: il patch M40 ha comunque corretto il problema autonomamente. La fix proattiva sarà disponibile per il prossimo run.

## Autonomia
~85% — solo 2 patch compile (autonome da M40) + 1 intervento manuale non necessario (il processo era già partito)

## Prossimo task

### Conway v3 (se necessario)
Con le lezioni apprese, v3 dovrebbe:
1. Compilare al primo tentativo (fix proattivi per uint8_t* grid)
2. Avere serial output corretto (delay(16) in loop())
3. Gestire stable → reinit
4. Essere valutato correttamente (anchor_done con eval_result)

### Snake Game su OLED SSD1306
- Testata con OLED: serpente cresce mangiando cibo, game over a bordo o auto-collisione
- Serial: SCORE:<n> GAMEOVER ogni partita
- Nessuna accelerazione hardware necessaria — loop semplice con delay(200ms)

## KB Lessons aggiunte questa sessione
- Conway bit packing (colonna=x/8, bit=x%8)
- Conway swap grids once per frame
- Conway serial timer in loop not printStatus
- Conway computeNextGeneration iterate xy direct
- Conway getCell/setCell parameter MUST be uint8_t grid[][16]

## Conferma hardware Conway v2
MI50-vision (03:37): "Il numero di celle vive (49) è costante nel tempo, indicando uno stato stabile. Le variazioni nei blob medi e nelle righe/colonne attive tra i frame sono coerenti con un sistema stabile che evolve minimamente, come previsto dal Game of Life. Il display OLED ha sfondo nero, come previsto, e i pixel bianchi luminosi sono presenti, confermando che il sistema funziona correttamente."
