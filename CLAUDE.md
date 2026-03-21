# Programmatore di Arduini — Istruzioni per Claude

## ⚡ INIZIO SESSIONE

All'inizio di ogni sessione Claude DEVE:
1. Leggere `STATO.md` — stato corrente del progetto
2. Leggere `PREFLIGHT.md` ed eseguire **tutti gli step** in ordine:
   - STEP 1: Test inferenza MI50 (chat reale, non solo health)
   - STEP 2: Test inferenza M40 (chat reale, non solo health)
   - STEP 3: Raspberry Pi raggiungibile + porta seriale libera
   - STEP 4: Webcam funzionante (grab_now → frame valido)
   - STEP 5: Dashboard attiva su porta 7700
   - STEP 6: Warm-up run (task semplice, Claude esegue i tool manualmente)
   - STEP 7: Ricerca KB per esempio simile al task reale
   - STEP 8: Preparare task con contesto completo per il programmatore
3. Se i servizi non sono attivi, avviarli:
   ```bash
   cd /home/lele/codex-openai/programmatore_di_arduini
   source .venv/bin/activate
   bash agent/start_servers.sh
   ```
   (`start_servers.sh` gestisce VRAM, check porta, kill processi bloccanti — NON avviare i server manualmente)
4. Riassumere lo stato a Lele con semaforo preflight e proporre cosa fare.

**REGOLA:** Claude NON lancia `python agent/tool_agent.py` finché tutti i check del PREFLIGHT non sono verdi.

---

## 🔴 FINE SESSIONE

Quando Lele dice che per oggi si finisce, Claude DEVE:
1. Aggiornare `STATO.md` con lo stato corrente (cosa funziona, cosa no, issues aperti)
2. Aggiornare `MEMORY.md` in `.claude/projects/.../memory/` se ci sono novità strutturali

---

## Contesto

Agente autonomo che genera codice Arduino/ESP32 da linguaggio naturale, lo compila,
lo carica sul hardware fisico via Raspberry Pi e valuta il risultato (testo + visione).

**Architettura GPU:**
- MI50 (ROCm): reasoning, planning, analisi errori, valutazione → `http://localhost:11434`
- M40 (CUDA): generazione codice veloce → `http://localhost:11435`

**Hardware remoto:**
- Raspberry Pi 3B: `lele@YOUR_RPI_IP` (pwd: YOUR_PASSWORD)
- ESP32: collegato via CP2102 a `/dev/ttyUSB0` sul Raspberry
- Webcam CSI: `/dev/video0` sul Raspberry

---

## Permessi espliciti

Claude può eseguire senza chiedere conferma (AUTONOMIA TOTALE):
- Leggere e modificare qualsiasi file in `programmatore_di_arduini/`
- Creare ed eliminare file e directory dentro `programmatore_di_arduini/`
- Lanciare `python agent/loop.py ...` per test
- Avviare/stoppare servizi MI50 e M40
- SSH/SCP sul Raspberry (`lele@YOUR_RPI_IP`) — qualsiasi operazione
- Leggere log in `logs/`
- `sqlite3 knowledge/arduino_agent.db` per ispezione e modifica KB
- Qualsiasi comando bash dentro `programmatore_di_arduini/`

Richiede conferma:
- Modificare il venv
- Operazioni fuori da `programmatore_di_arduini/` (eccetto Raspberry)
- Push su git (se il repo fosse configurato)

---

## Regole operative

- **MAI toccare project_jedi** — progetto separato e isolato
- **MAI installare pacchetti** nel venv senza conferma
- Il venv è `.venv/` — attivare sempre con `source .venv/bin/activate`
- MI50 e M40 devono essere avviati come server prima di qualsiasi run
- Per ESP32: baud rate 115200, FQBN `esp32:esp32:esp32`
- Per Arduino AVR: baud rate 9600, FQBN `arduino:avr:uno`

## Regole fondamentali — stabilite 2026-03-19

### LOGGING: ogni run va archiviata
- I log delle run NON vanno in `/tmp` — vanno in `logs/runs/<timestamp>_<task>/`
- Ogni run deve salvare: log completo, codice per ogni versione, errori compilazione,
  output seriale, frame webcam, risultato finale in `result.json`
- Lo scopo è avere riscontro storico dell'avanzamento e dei bug ricorrenti

### RESUME: mai ricominciare da capo
- Se una run incontra un bug o un errore, si corregge il problema e si riparte
  dall'ultimo checkpoint valido — MAI ripartire da `plan_task`
- La sessione va serializzata su disco dopo ogni fase completata con successo
- Il resume deve essere possibile con: `python agent/tool_agent.py --resume <run_dir>`
- Questa regola vale anche per Claude: se il tool_agent crasha, Claude corregge
  il bug e fa ripartire dal checkpoint, non rilancia da zero

---

## Comandi utili

```bash
# Run completo ESP32
python agent/loop.py "task" --fqbn esp32:esp32:esp32

# Solo compilazione (no hardware)
python agent/loop.py "task" --fqbn esp32:esp32:esp32 --no-upload

# Verifica Raspberry
python -c "from agent.remote_uploader import is_reachable; print(is_reachable())"

# Porta seriale sul Raspberry
ssh lele@YOUR_RPI_IP "ls /dev/ttyUSB* 2>/dev/null; fuser /dev/ttyUSB0 2>/dev/null && echo BUSY || echo FREE"

# Ultimo log
tail -f logs/$(ls -t logs/ | head -1)

# Knowledge base
sqlite3 knowledge/arduino_agent.db "SELECT task_description, board, created_at FROM snippets ORDER BY created_at DESC LIMIT 5;"
```
