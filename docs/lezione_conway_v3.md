# Lezione: Conway Game of Life v3 — 2026-03-22 mattina (ore ~05:00-05:45)

## Stato finale
- **Compilazione**: OK (compile #2 — dopo 1 patch)
- **Upload**: OK
- **Serial**: `Generation:0\nAlive:463\nStable:0` (1 ciclo in 10s)
- **Valutazione**: evaluate_visual: success=True [serial-first] — Generation/Alive/Stable trovati
- **Run end**: ❌ FAILED (ancora — bug `done` JSON senza `"success":true`)
- **result.json**: success=True

## Miglioramenti rispetto a v2
| v2 Bug | v3 Status |
|--------|-----------|
| `uint8_t* grid` invece di `uint8_t grid[][16]` | ✅ M40 ha usato la firma corretta (SYSTEM_FUNCTION insegnata) |
| Backtick in patch | ✅ non presente |
| Serial spam (80142 righe/10s) | ✅ RISOLTO — solo 3 righe in 10s (delay(16) funziona!) |
| Stable→reinit non gestito | ⚠️ non verificato (serial mostra solo gen 0) |

## Bug M40 in v3

### Bug 1: `bool isStable` come variabile globale E come funzione
**Causa**: M40 ha dichiarato `bool isStable = false` nella sezione globals, e poi anche `bool isStable()` come funzione.
**Errore**: `'bool isStable()' redeclared as different kind of entity` (2 errori).
**Fix applicato**: patch M40 al compile #2 — rinominata variabile globale in `bool isStableState = false`.
**Fix sistemico necessario**: aggiungere regola in SYSTEM_FUNCTION: "NON usare lo stesso nome per variabile globale e funzione — es. usa `isStableState` per la variabile e `checkStability()` per la funzione".

### Bug 2: `setPixel` invece di `drawPixel`
**Causa**: `Adafruit_SSD1306` non ha `setPixel` — il metodo corretto è `drawPixel(x, y, color)`.
**Errore**: `'class Adafruit_SSD1306' has no member named 'setPixel'; did you mean 'getPixel'?`
**Fix applicato**: patch M40 — sostituito con `drawPixel`.
**Fix sistemico**: aggiungere a `fix_known_api_errors()` in compiler.py: `setPixel` → `drawPixel`.

## Bug sistemici pipeline scoperti questa sessione

### Bug: `done` JSON senza `success=true` → run segnata FAILED anche se eval=True
**Causa**: `_anchor_done` diceva "chiudi con `{"done": true}`" senza specificare `"success": true`.
**Effetto**: MI50 manda `{"done": true}` senza success → `bool(parsed.get("success", False))` = False → RUN FAILED.
**Fix**: `_anchor_done` ora mostra il JSON esatto da usare: `{"done": true, "success": true/false, "reason": "..."}`.
**Commit**: `7eab4a2`

## Autonomia
~90% — solo 1 patch compile (autonoma da M40), zero intervento manuale

## Fix sistemici applicati durante la sessione (in aggiunta ai Conway v3)
- **Loop detection**: MI50 che chiama stesso tool 3× → hint forzato nel context
- **plan_task guard**: fasi avanzate restituiscono piano già fatto + hint "chiama upload_and_read"
- **Checkpoint atomico**: write su .tmp + replace (previene corruzione in caso di crash)
- **learner iterations**: ora legge `sess.logger._compile_errors` (era sempre vuoto prima)
- **Double index_lesson**: rimosso secondo `index_lesson` nel learner (add_lesson lo fa già)
- **anchor_done success**: JSON esplicito con success=true/false derivato da eval_result

## Prossimo task: Snake Game su OLED SSD1306
- Serpente cresce mangiando cibo, game over a bordo o auto-collisione
- Serial: `SCORE:<n>` + `GAMEOVER` ogni partita
- Nessuna accelerazione hardware necessaria — loop con delay(200ms)
- Regole importanti da includere nel task:
  - display.drawPixel → NON setPixel
  - NON usare stesso nome per variabile globale e funzione
  - Serial.println() per terminare ogni riga del serial
