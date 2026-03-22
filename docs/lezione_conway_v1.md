# Lezione: Conway Game of Life v1 — 2026-03-22 notte

## Stato finale
- **Compilazione**: OK (compile #1 — proactive fixes hanno funzionato)
- **Upload**: OK
- **Simulazione hardware**: PARZIALMENTE funzionante (display mostra pixel bianchi in movimento)
- **Valutazione autonoma**: ❌ FALLITO — MI50 in done phase vede GEN:229 ALIVE:204 × 40019 e conclude "simulation stuck"

## Timeline run
- `01:49` — launch Conway v1
- `02:14` — generate_all_functions completa → 237 righe
- `02:15` — compile #1 → OK (proactive dist()+drawCircle fix)
- `02:15` — upload → OK
- `02:16` — evaluate_visual → M40 VisualJudge: success=True ("pixel pattern matches Game of Life")
- `02:23` — done → MI50: {done:true, success:false} ("simulation appears stuck at GEN:229")

## Bug nel codice generato da M40

### Bug 1: Double swapGrids() — CRITICO
**Causa**: `computeNextGeneration()` chiama `swapGrids()` all'interno (riga 119), e `loop()` la chiama di nuovo (riga 227).
**Effetto**: il grid oscilla tra due stati ogni frame. La simulazione non avanza mai, rimane nel ciclo 2-step.
**Fix**: `computeNextGeneration()` NON deve chiamare `swapGrids()`. Solo `loop()` la chiama, una volta per frame.

### Bug 2: Bit packing inconsistente in initRandomGrid()
**Causa**: `bitIndex = x % BITMAP_COLS` (= x%16) per la colonna, `x / BITMAP_COLS` (= x/16) per il bit.
**Corretto**: colonna = x/8 (0..15), bit = x%8 (0..7).
**Effetto**: celle inizializzate nelle posizioni sbagliate. `drawGrid()` usa x/8 per colonna → schema random iniziale non corrisponde a quello disegnato.
**Fix**: usare SEMPRE colonna=x/8, bit=x%8 in TUTTI i metodi. Helper `getCell(g,x,y)` e `setCell(g,x,y,v)`.

### Bug 3: checkStability() usa bit order inverso
**Causa**: riga 160: `(currentGrid[y][x / 8] >> (7 - (x % 8))) & 1` — usa `7-(x%8)` invece di `x%8`.
**Effetto**: la stability check confronta bit in ordine inverso rispetto a tutto il resto → risultati errati.
**Fix**: usare `getCell()` helper per consistenza.

### Bug 4: gridX sbagliato in computeNextGeneration()
**Causa**: riga 87: `int gridX = (y * BITMAP_COLS) + bitCol` — produce coordinate fuori range e sbagliate.
**Fix**: iterare su `for(int y=0; y<GRID_H; y++) for(int x=0; x<GRID_W; x++)` e usare `getCell(currentGrid, x, y)` direttamente.

### Bug 5: Serial spam (conseguenza del double swap)
**Causa**: il double swap fa oscillare il grid → `checkStability()` a volte dice stable (false positive) → `printStatus()` chiama `initRandomGrid()` → reset generation=0 → conta su a 229 di nuovo → ciclo.
**Effetto**: `GEN:229 ALIVE:204` ripetuto × 40019 in 10 secondi → serial pieno di spam → MI50 conclude "stuck".

## Bug sistemici nel pipeline

### Bug 6: MI50 in done phase vede serial spam → falso negativo
**Causa**: `_anchor_done` mostrava le ultime 8 righe raw del serial → 8 righe identiche `GEN:229 ALIVE:204`.
**Fix**: `_anchor_done` ora usa `_serial_summary()` (deduplication) + mostra `eval_result` esplicito.
**Esempio anchor_done corretto**: `VALUTAZIONE: success=True [opencv+m40] — pixel pattern matches Game of Life`

### Bug 7: Lezioni aggiunte a SQLite ma non a ChromaDB → not found in semantic search
**Causa**: `db.add_lesson()` scriveva solo in SQLite, non chiamava `index_lesson()` per ChromaDB.
**Fix**: `db.add_lesson()` ora chiama `semantic.index_lesson()` automaticamente.

## Fix sistemici apportati questa sessione

1. **SYSTEM_FUNCTION** in `generator.py`: 4 nuove regole Conway (bit packing, swap, serial timer, iterate xy)
2. **`_patch_code`** in `tool_agent.py`: KB lessons iniettate nel contesto M40 patcher
3. **`_anchor_compiling`**: KB lessons iniettate quando ci sono errori (SQLite fallback)
4. **`_anchor_done`**: mostra `eval_result` + `_serial_summary()` invece di serial raw
5. **`_Session.eval_result`**: campo per salvare risultato evaluate_visual/text
6. **`_generate_all_functions`**: stub detection (// TODO, // Implement → warn MI50)
7. **system prompt**: documenta `expected_events` in `evaluate_visual` (serial-first)
8. **`db.add_lesson`**: auto-sync a ChromaDB

## KB Lessons aggiunte
- `conway_bit_packing_must_use_x_div_8`
- `conway_swap_grids_once_per_frame_in_loop`
- `conway_serial_millis_timer_in_loop_not_printStatus`
- `conway_compute_next_gen_use_xy_direct`

## Risultato parziale confermato
- OLED acceso con pixel bianchi visibili: ✅ (M40 VisualJudge: success=True)
- Serial: `GEN:229 ALIVE:204` × 40019 (spam da double swap bug)
- La simulazione gira ma con comportamento errato (double swap = 2-cycle oscillation)

## Conway v2
Lanciata questa notte con task description corretto (tutte le regole specificate).
Run: `logs/runs/20260322_024218_Conway_s_Game_of_Life_su_OLED_SSD1306_12`
