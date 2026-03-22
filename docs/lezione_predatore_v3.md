# Lezione: Predatore v3 — Boids con morte/respawn (2026-03-22)

## Stato finale
- **Compilazione**: OK (con fix manuali)
- **Upload**: OK
- **Simulazione hardware**: PARZIALMENTE funzionante (HUNT/CATCH visibili, ma bug nel respawn)
- **Valutazione autonoma**: ❌ falso negativo (evaluator vede solo RESPAWN:0 spam iniziale)

## Timeline run
- `00:26` — launch predatore v3 con task completo
- `00:57` — compile #1 fallisce: `dist()` non dichiarata + `drawCircle(float)`
- `01:01-01:13` — 3x patch_code → tutti rifiutati (regressione 295→49 righe)
- `01:13` — compile #2 fallisce ancora (processo aveva OLD compiler.py prima del commit 00:31)
- `01:27` — [RESUME manuale] fix dist()+drawCircle applicati manualmente → compile #4 OK
- `01:28` — upload → seriale: RESPAWN:0 × 5000+ poi HUNT/CATCH visibili
- `01:33` — evaluate_visual → success:false (vede solo spam iniziale)
- `01:37` — done (con anchor_done fix)

## Bug nel codice generato da M40

### Bug 1: `predator.id = nextPreyId++` → OOB
**Causa**: dopo init 8 prede (IDs 0-7), `nextPreyId=8`. Poi `predator.id = 8` → `prey[8]` OOB.
**Effetto**: predatore punta a memoria casuale, comportamento imprevedibile.
**Fix**: `predator.id = 0;` o `predator.id = findNearestPrey();` — NON usare nextPreyId.

### Bug 2: `lastRespawnTime` globale condiviso
**Causa**: tutte le prede condividono un solo timer → catena di respawn sbagliata.
**Fix**: campo `unsigned long respawnTime` per-preda in struct `Boid`.

### Bug 3: `spawnPrey()` usa `nextPreyId` ciclico per il respawn
**Causa**: `nextPreyId` ciclico → rispawna sempre `prey[0]` (anche se è viva) → `RESPAWN:0` loop.
**Fix**: `respawnPrey(int i)` con indice esplicito della preda morta.

### Bug 4: Serial.print senza newline finale
**Causa**: HUNT line termina con `Serial.print(fleeCount)` non `println` → CATCH si concatena.
**Effetto**: `HUNT:3 DIST:45.2 FLEE:1CATCH:3` sulla stessa riga.
**Fix**: `Serial.println(fleeCount)` per terminare la riga HUNT.

## Bug sistemici scoperti nel tool_agent

### Bug 5: Fix non applicato in compile #2 (processo con OLD codice)
**Causa**: il processo Python partì alle 00:26, il commit con `_fix_dist_function` fu alle 00:31.
Python ha compilato il vecchio compiler.py in memoria → fix non disponibile.
**Implicazione**: ogni volta che si modifica compiler.py/tool_agent.py durante una run, il processo in esecuzione usa ancora il vecchio codice. Riavviare il processo dopo ogni commit.

### Bug 6: Fase `done` senza anchor
**Causa**: `_build_anchor()` non aveva il caso `PHASE_DONE` → fallback a `_anchor_planning`.
**Effetto**: MI50 in fase done vede l'anchor di planning + ctx con errori vecchi → continua a chiamare patch_code.
**Fix**: aggiunto `_anchor_done()` con ISTRUZIONE esplicita: `save_to_kb` poi `{done:true}`.

## Lezioni sistemiche aggiunte

1. **predator_id_must_be_prey_target_index** → SYSTEM_FUNCTION + KB
2. **boids_per_prey_respawn_timer** → SYSTEM_FUNCTION + KB
3. **boids_respawn_use_explicit_prey_index** → SYSTEM_FUNCTION + KB
4. **serial_println_terminate_hunt_line** → SYSTEM_FUNCTION + KB
5. **anchor_done** → `_anchor_done()` aggiunto in tool_agent.py

## Risultato parziale confermato
- OLED con 8 cerchi (prede) + 1 cerchio grande (predatore): VISIBILE
- Serial mostra HUNT:8 DIST:132.97 FLEE:0, poi CATCH:1, poi RESPAWN:0...
- La simulazione gira, ma con i 4 bug sopra che rendono il comportamento errato

## Prossimo task
Conway's Game of Life su OLED SSD1306 128x64, con wrap-around bordi, start con pattern Gosper Glider Gun.
