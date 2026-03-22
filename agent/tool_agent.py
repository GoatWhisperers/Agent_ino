"""
Tool Agent — agente ReAct MI50 + M40 con context management MemGPT-style.

Architettura:
  - MI50 ragiona, pianifica, usa tools, valuta
  - M40 genera tutto il codice (mai MI50)
  - Context = [system] + [anchor fase-specifico] + [sliding window 5 turni]
  - Anchor phase-aware: planning / generating / compiling / uploading / evaluating
  - Ogni run archiviata in logs/runs/<ts>_<task>/
  - Checkpoint dopo ogni tool call → resume con --resume <run_dir>

Avvio:
    python agent/tool_agent.py "task" [--fqbn esp32:esp32:esp32] [--max-steps 30]
    python agent/tool_agent.py --resume logs/runs/20260319_093700_pallina/
"""

import argparse
import json
import os
import re
import sys
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Singleton lock — impedisce istanze multiple ───────────────────────────────

_LOCK_FILE = Path("/tmp/tool_agent.lock")

def _acquire_lock() -> bool:
    """Ritorna True se il lock è acquisito, False se un'altra istanza è attiva."""
    if _LOCK_FILE.exists():
        try:
            pid = int(_LOCK_FILE.read_text().strip())
            # Verifica se il processo esiste ancora
            os.kill(pid, 0)
            return False  # processo vivo → istanza attiva
        except (ProcessLookupError, ValueError):
            pass  # processo morto → lock stantio, lo sovrascriviamo
    _LOCK_FILE.write_text(str(os.getpid()))
    return True

def _release_lock():
    try:
        if _LOCK_FILE.exists() and _LOCK_FILE.read_text().strip() == str(os.getpid()):
            _LOCK_FILE.unlink()
    except Exception:
        pass

from agent.mi50_client import MI50Client

# ── Dashboard helper ─────────────────────────────────────────────────────────

_DASH_URL = "http://localhost:7700/emit"


def _dash(event_type: str, **kwargs):
    try:
        import requests
        requests.post(_DASH_URL, json={"type": event_type, **kwargs}, timeout=2)
    except Exception:
        pass


def _phase(name: str, detail: str = ""):
    _dash("phase", name=name, detail=detail)


def _serial_summary(serial: str, max_chars: int = 600) -> str:
    """
    Riassume il serial output per MI50: evita di mostrare solo spam iniziale.
    Strategia: deduplica righe consecutive identiche + mostra inizio + fine.
    """
    if not serial:
        return ""
    lines = [l for l in serial.splitlines() if l.strip()]
    if not lines:
        return ""

    # Deduplica righe consecutive identiche, sostituendo con "× N"
    deduped = []
    i = 0
    while i < len(lines):
        count = 1
        while i + count < len(lines) and lines[i + count] == lines[i]:
            count += 1
        if count > 3:
            deduped.append(f"{lines[i]} [× {count}]")
        else:
            deduped.extend(lines[i:i + count])
        i += count

    # Mostra prime 5 righe deduplicate + ultime 8 righe originali (per vedere eventi recenti)
    head = deduped[:5]
    tail_raw = lines[-8:] if len(lines) > 8 else []
    if tail_raw and deduped[-1:] != tail_raw[-1:]:
        summary = "\n".join(head)
        if tail_raw:
            summary += "\n...\n" + "\n".join(tail_raw)
    else:
        summary = "\n".join(deduped)

    return summary[:max_chars]


def _frame(path: str, label: str = "agent"):
    _dash("frame", path=path, label=label)


# ── System prompt — corto e duro ─────────────────────────────────────────────

_SYSTEM = """\
Sei un agente autonomo per Arduino/ESP32.

REGOLA 1 — UNA SOLA AZIONE PER RISPOSTA. Rispondi con UN SOLO oggetto JSON, poi aspetta il risultato.
REGOLA 2 — NON scrivere MAI codice negli args. M40 genera tutto il codice.
REGOLA 3 — generate_globals e generate_all_functions usano args:{} (nessun parametro).
REGOLA 4 — SE il messaggio di sistema dice ISTRUZIONE: chiama ESATTAMENTE quel tool. NON fare altro.
REGOLA 5 — NON richiamare plan_task/plan_functions/generate_globals se sei già in fase upload o evaluate.
REGOLA 6 — Se plan_task restituisce {"skipped":true}, il piano è già pronto. Chiama SUBITO il tool indicato in "reason".

FORMATO (scegli UNO):
  Tool call : {"tool":"nome","args":{...},"reason":"perché"}
  Fine task : {"done":true,"success":bool,"reason":"spiegazione"}

FLUSSO (un passo alla volta, aspetta il risultato prima di procedere):
  1. plan_task
  2. plan_functions
  3. generate_globals
  4. generate_all_functions    ← M40 genera tutto in parallelo
  5. compile
     se errori → patch_code → compile  (max 3 cicli)
     patch_code args: {"errors": [...], "analysis": "descrizione fix"}
     M40 riscrive il codice correggendo gli errori — NON serve analyze_errors prima
  6. upload_and_read           ← se il messaggio dice "pronto per upload", chiama QUESTO
  7. OBBLIGATORIO se il task usa OLED/display: grab_frames → evaluate_visual
     ⚠ NON saltare evaluate_visual per task display — serve vedere il risultato con gli occhi
     evaluate_visual args: {"expected_events": ["GEN:", "ALIVE:", "HIT", ecc.]} — se serial contiene questi → success immediato (serial-first)
     ALTRIMENTI (solo LED, solo seriale, nessun display): evaluate_text
  8. save_to_kb
  9. {"done":true,...}

HARDWARE: ESP32 NodeMCU esp32:esp32:esp32 | OLED SSD1306 128x64 I2C addr=0x3C solo WHITE | LED GPIO2
WEBCAM: inquadra il display OLED — chiamare grab_frames PRIMA di evaluate_visual\
"""


# ── RunLogger — archivia ogni run in logs/runs/<ts>_<slug>/ ──────────────────

class RunLogger:
    """
    Archivia tutto quello che produce una run:
      logs/runs/<YYYYMMDD_HHMMSS>_<task_slug>/
        run.log            — log testuale completo
        meta.json          — task, fqbn, start/end, success
        plan.json          — output plan_task + plan_functions
        code_v1.ino        — codice dopo generate_all_functions
        code_v2_patch.ino  — codice dopo ogni patch
        compile_errors.json — errori per ogni tentativo
        serial_output.txt  — output seriale ESP32
        frame_NNN.jpg      — frame webcam copiati
        result.json        — {success, reason, suggestions}
        checkpoint.json    — sessione serializzata (aggiornato ogni step)
    """

    def __init__(self, task: str, run_dir: Path = None):
        if run_dir is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug = re.sub(r"[^\w]+", "_", task[:40]).strip("_")
            run_dir = Path(__file__).parent.parent / "logs" / "runs" / f"{ts}_{slug}"
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._log_fh = open(self.run_dir / "run.log", "a", encoding="utf-8", buffering=1)
        self._code_version = 0
        self._compile_errors = []

    def log(self, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_fh.write(f"[{ts}] {text}\n")

    def save_code(self, code: str, label: str = ""):
        self._code_version += 1
        name = f"code_v{self._code_version}" + (f"_{label}" if label else "")
        (self.run_dir / f"{name}.ino").write_text(code, encoding="utf-8")
        self.log(f"CODE saved: {name}.ino ({len(code.splitlines())} righe)")

    def save_json(self, data: dict, name: str):
        (self.run_dir / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def save_frame(self, src_path: str, idx: int = None) -> str:
        src = Path(src_path)
        label = f"frame_{idx:03d}.jpg" if idx is not None else src.name
        dst = self.run_dir / label
        shutil.copy2(src, dst)
        return str(dst)

    def add_compile_errors(self, attempt: int, errors: list):
        self._compile_errors.append({"attempt": attempt, "errors": errors})
        self.save_json(self._compile_errors, "compile_errors")

    def close(self, success: bool = None, reason: str = ""):
        if success is not None:
            self.log(f"RUN END — {'✅ SUCCESS' if success else '❌ FAILED'}: {reason}")
        self._log_fh.close()

    @property
    def path(self) -> Path:
        return self.run_dir


# ── Stato sessione ────────────────────────────────────────────────────────────

class _Session:
    # Fasi del flusso — determinano quale anchor viene costruito
    PHASE_PLANNING   = "planning"    # plan_task, plan_functions
    PHASE_GENERATING = "generating"  # generate_globals, generate_all_functions
    PHASE_COMPILING  = "compiling"   # compile, patch_code
    PHASE_UPLOADING  = "uploading"   # upload_and_read
    PHASE_EVALUATING = "evaluating"  # grab_frames, evaluate_*
    PHASE_DONE       = "done"        # save_to_kb, {done:true}

    def __init__(self, task: str, fqbn: str):
        self.task = task
        self.fqbn = fqbn
        self.nb = None
        self.sketch_dir = None
        self.code = ""
        self.errors = []
        self.serial = ""
        self.frame_paths = []
        self.compile_attempts = 0
        self.kb_example = ""        # snippet funzionante dalla KB, passato a M40
        self.lessons_context = ""   # lessons dalla KB, iniettate in plan_task e plan_functions
        self.phase = self.PHASE_PLANNING
        self.plan_result = {}       # output di plan_task, usato nell'anchor generating
        self.eval_result = {}       # risultato evaluate_visual/evaluate_text — usato in _anchor_done
        self.logger: RunLogger = None  # impostato da run()

    def set_phase(self, phase: str):
        self.phase = phase
        if self.logger:
            self.logger.log(f"PHASE → {phase.upper()}")

    def write_sketch(self, code: str):
        from agent.compiler import fix_known_includes
        code = fix_known_includes(code)
        self.code = code
        if self.sketch_dir is None:
            self.sketch_dir = Path(tempfile.mkdtemp(prefix="tool_agent_"))
        ino = self.sketch_dir / f"{self.sketch_dir.name}.ino"
        ino.write_text(code, encoding="utf-8")

    def cleanup(self):
        if self.sketch_dir:
            shutil.rmtree(self.sketch_dir, ignore_errors=True)

    def to_dict(self) -> dict:
        """Serializza la sessione per il checkpoint."""
        nb_data = None
        if self.nb is not None:
            nb_data = {
                "globals_hint": self.nb.globals_hint,
                "globals_code": self.nb.globals_code,
                "funzioni":     self.nb.funzioni,
            }
        return {
            "task":             self.task,
            "fqbn":             self.fqbn,
            "code":             self.code,
            "errors":           self.errors,
            "serial":           self.serial,
            "frame_paths":      self.frame_paths,
            "compile_attempts": self.compile_attempts,
            "kb_example":       self.kb_example,
            "lessons_context":  self.lessons_context,
            "phase":            self.phase,
            "plan_result":      self.plan_result,
            "eval_result":      self.eval_result,
            "nb":               nb_data,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "_Session":
        """Ricostruisce la sessione da un checkpoint."""
        s = cls(task=d["task"], fqbn=d["fqbn"])
        s.code             = d.get("code", "")
        s.errors           = d.get("errors", [])
        s.serial           = d.get("serial", "")
        s.frame_paths      = d.get("frame_paths", [])
        s.compile_attempts = d.get("compile_attempts", 0)
        s.kb_example       = d.get("kb_example", "")
        s.lessons_context  = d.get("lessons_context", "")
        s.phase            = d.get("phase", cls.PHASE_PLANNING)
        s.plan_result      = d.get("plan_result", {})
        s.eval_result      = d.get("eval_result", {})
        # Ricrea Notebook dal checkpoint se salvato
        nb_data = d.get("nb")
        if nb_data:
            from agent.notebook import Notebook
            s.nb = Notebook(task=s.task, board=s.fqbn)
            # set_funzioni inizializza stato="pending" e codice="" per ogni funzione
            s.nb.set_funzioni(
                globals_hint=nb_data.get("globals_hint", ""),
                funzioni=nb_data.get("funzioni", []),
            )
            # Ripristina stato/codice già generati (per resume mid-generation)
            saved_by_nome = {f["nome"]: f for f in nb_data.get("funzioni", [])}
            for f in s.nb.funzioni:
                saved = saved_by_nome.get(f["nome"], {})
                if saved.get("codice"):
                    f["codice"] = saved["codice"]
                    f["stato"]  = saved.get("stato", "done")
            s.nb.globals_code = nb_data.get("globals_code", "")
        # Ricrea lo sketch_dir se c'è codice
        if s.code:
            s.sketch_dir = Path(tempfile.mkdtemp(prefix="tool_agent_resume_"))
            ino = s.sketch_dir / f"{s.sketch_dir.name}.ino"
            ino.write_text(s.code, encoding="utf-8")
        return s


# ── Context Manager — MemGPT-style, anchor phase-aware ───────────────────────

class _ContextManager:
    """
    Mantiene un contesto piccolo e stabile:
      [system] + [anchor FASE-SPECIFICO] + [ultimi MAX_TURNS turni]

    L'anchor cambia in base alla fase:
      planning   → task completo, nessun codice
      generating → task + piano funzioni
      compiling  → solo errori + righe di codice coinvolte
      uploading  → task + stato "pronto"
      evaluating → task + serial + frame paths
    """
    MAX_TURNS = 5

    def __init__(self, task: str, fqbn: str):
        self.task = task
        self.fqbn = fqbn
        self._turns: list[tuple[str, str]] = []
        self._summary: list[str] = []

    def add_turn(self, assistant_raw: str, tool_name: str, result_str: str):
        user_content = f"Risultato {tool_name}:\n{result_str}"
        self._turns.append((assistant_raw, user_content))
        while len(self._turns) > self.MAX_TURNS:
            old_a, old_u = self._turns.pop(0)
            try:
                cleaned = re.sub(r"<think>.*?</think>", "", old_a, flags=re.DOTALL).strip()
                call = json.loads(cleaned)
                tn = call.get("tool", "?")
            except Exception:
                tn = "?"
            prefix = f"Risultato {tn}:\n"
            result_short = old_u[len(prefix):].strip()[:120].replace("\n", " ")
            self._summary.append(f"✓ {tn}: {result_short}")

    def build_messages(self, sess: _Session) -> list[dict]:
        anchor = self._build_anchor(sess)
        msgs = [{"role": "system", "content": _SYSTEM}]
        msgs.append({"role": "user", "content": anchor})
        for assist, user in self._turns:
            msgs.append({"role": "assistant", "content": assist})
            msgs.append({"role": "user", "content": user})
        return msgs

    # ── Anchor phase-aware ────────────────────────────────────────────────────

    def _build_anchor(self, sess: _Session) -> str:
        phase = sess.phase
        if phase == _Session.PHASE_PLANNING:
            return self._anchor_planning(sess)
        elif phase == _Session.PHASE_GENERATING:
            return self._anchor_generating(sess)
        elif phase == _Session.PHASE_COMPILING:
            return self._anchor_compiling(sess)
        elif phase == _Session.PHASE_UPLOADING:
            return self._anchor_uploading(sess)
        elif phase == _Session.PHASE_EVALUATING:
            return self._anchor_evaluating(sess)
        elif phase == _Session.PHASE_DONE:
            return self._anchor_done(sess)
        else:
            return self._anchor_planning(sess)  # fallback

    def _anchor_planning(self, sess: _Session) -> str:
        """Fase planning: task completo, nessun codice."""
        parts = [f"TASK: {sess.task}\nBOARD: {sess.fqbn}"]
        if self._summary:
            parts.append("COMPLETATI:\n" + "\n".join(self._summary))
        return "\n\n".join(parts)

    def _anchor_generating(self, sess: _Session) -> str:
        """Fase generating: task breve + piano (approach + funzioni)."""
        parts = [f"TASK: {sess.task[:100]}\nBOARD: {sess.fqbn}"]
        if self._summary:
            parts.append("COMPLETATI:\n" + "\n".join(self._summary[-3:]))
        if sess.plan_result:
            approach = sess.plan_result.get("approach", "")
            libs = sess.plan_result.get("libraries_needed", [])
            if approach:
                parts.append(f"APPROCCIO: {approach}")
            if libs:
                parts.append(f"LIBRERIE: {', '.join(libs)}")
        # Mostra lista funzioni pianificate — aiuta MI50 a non chiamare plan_functions di nuovo
        if sess.nb and sess.nb.funzioni:
            nomi = [f.get("nome", "?") for f in sess.nb.funzioni]
            parts.append(f"FUNZIONI PIANIFICATE (già complete): {', '.join(nomi)}")
            parts.append("⚠ plan_task e plan_functions sono GIÀ STATI eseguiti. Prossimo step: generate_globals")
        return "\n\n".join(parts)

    def _anchor_compiling(self, sess: _Session) -> str:
        """Fase compiling: solo errori + righe di codice coinvolte. Niente codice completo."""
        parts = [
            f"TASK: {sess.task[:80]}\nBOARD: {sess.fqbn}"
            f"\nTENTATIVO COMPILAZIONE: {sess.compile_attempts}"
        ]
        if self._summary:
            parts.append("COMPLETATI:\n" + "\n".join(self._summary[-2:]))
        if sess.errors:
            err_lines = "\n".join(str(e) for e in sess.errors[:5])
            parts.append(f"ERRORI COMPILATORE:\n{err_lines}")
        if sess.code:
            relevant = self._extract_relevant_code(sess)
            if relevant:
                parts.append(f"CODICE (sezioni con errori):\n```cpp\n{relevant}\n```")
        # Inietta lezioni KB rilevanti (dal contesto di sessione o ricerca fresca)
        lessons_hint = sess.lessons_context
        if not lessons_hint and sess.errors:
            try:
                error_text = " ".join(
                    (e if isinstance(e, str) else e.get("message", ""))
                    for e in sess.errors[:3]
                )
                from knowledge.db import search_lessons as db_lessons
                lessons = db_lessons(f"{sess.task[:60]} {error_text[:150]}", limit=2)
                if lessons:
                    hints = [l.get('lesson', '')[:120] for l in lessons]
                    lessons_hint = "\n".join(f"- {h}" for h in hints if h)
            except Exception:
                pass
        if lessons_hint:
            parts.append(f"LEZIONI KB (considera queste soluzioni):\n{lessons_hint[:400]}")
        return "\n\n".join(parts)

    def _anchor_uploading(self, sess: _Session) -> str:
        """Fase uploading: task + conferma che il codice compila."""
        parts = [
            f"TASK: {sess.task[:80]}\nBOARD: {sess.fqbn}\n"
            f"STATO: codice compilato correttamente, pronto per upload su ESP32.\n"
            f"ISTRUZIONE CRITICA: chiama SUBITO upload_and_read con args:{{}}. "
            f"NON chiamare plan_task, plan_functions, generate_globals o generate_all_functions — "
            f"il codice è già completo e compilato. L'unico passo rimasto è l'upload sull'hardware."
        ]
        if self._summary:
            parts.append("COMPLETATI:\n" + "\n".join(self._summary[-2:]))
        return "\n\n".join(parts)

    def _anchor_evaluating(self, sess: _Session) -> str:
        """Fase evaluating: task + output seriale + frame. Niente codice."""
        parts = [
            f"TASK: {sess.task[:80]}\nBOARD: {sess.fqbn}\n"
            f"STATO: codice caricato sull'ESP32, serial e frame disponibili.\n"
            f"ISTRUZIONE: chiama evaluate_visual o evaluate_text per valutare il risultato. "
            f"NON chiamare plan_task, generate_globals o generate_all_functions."
        ]
        if self._summary:
            parts.append("COMPLETATI:\n" + "\n".join(self._summary[-2:]))
        if sess.serial:
            parts.append(f"OUTPUT SERIALE:\n{_serial_summary(sess.serial)}")
        if sess.frame_paths:
            parts.append(f"FRAME WEBCAM: {len(sess.frame_paths)} frame disponibili")
        return "\n\n".join(parts)

    def _anchor_done(self, sess: _Session) -> str:
        """Fase done: valutazione completata, salva in KB e chiudi."""
        serial_hint = ""
        if sess.serial:
            serial_hint = f"\nOUTPUT SERIALE (riassunto):\n{_serial_summary(sess.serial, max_chars=400)}"

        eval_hint = ""
        if sess.eval_result:
            ev_success = sess.eval_result.get("success", "?")
            ev_reason = sess.eval_result.get("reason", "")
            ev_pipeline = sess.eval_result.get("pipeline", "")
            eval_hint = f"\nVALUTAZIONE: success={ev_success} [{ev_pipeline}] — {ev_reason[:120]}"

        # Determina il valore di success da mostrare nell'anchor
        ev_success_val = sess.eval_result.get("success", False) if sess.eval_result else False
        success_str = "true" if ev_success_val else "false"

        parts = [
            f"TASK: {sess.task[:80]}\nBOARD: {sess.fqbn}\n"
            f"STATO: valutazione completata.{eval_hint}{serial_hint}\n"
            f"ISTRUZIONE CRITICA:\n"
            f"1. Chiama save_to_kb (args:{{}}) per salvare i pattern appresi.\n"
            f"2. Poi chiudi con ESATTAMENTE questo JSON (success DEVE riflettere la valutazione):\n"
            f'   {{"done": true, "success": {success_str}, "reason": "<descrizione breve del risultato>"}}\n'
            f"NON richiamare compile, patch_code, upload_and_read o evaluate_*. "
            f"La valutazione è già stata completata — non rivalutare."
        ]
        return "\n\n".join(parts)

    def _extract_relevant_code(self, sess: _Session) -> str:
        """Estrae solo le righe di codice vicine agli errori — non il codice completo."""
        lines = sess.code.splitlines()
        if not sess.errors:
            # Nessun errore preciso: mostra solo gli include
            includes = [l for l in lines if l.strip().startswith("#include")]
            return "\n".join(includes[:8])

        error_line_nums = set()
        for e in sess.errors[:3]:
            ln = e.get("line", 0) if isinstance(e, dict) else 0
            if ln > 0:
                error_line_nums.update(range(max(0, ln - 4), min(len(lines), ln + 3)))

        if not error_line_nums:
            # Errori senza numero di riga: include + prime 8 righe
            includes = [l for l in lines if l.strip().startswith("#include")]
            return "\n".join(includes[:8]) + "\n// ..."

        result = []
        prev = -2
        for i in sorted(error_line_nums):
            if i > prev + 1 and result:
                result.append("// ...")
            result.append(f"{i+1:3}: {lines[i]}")
            prev = i
        return "\n".join(result)

    def to_dict(self) -> dict:
        return {
            "task":     self.task,
            "fqbn":     self.fqbn,
            "_turns":   self._turns,
            "_summary": self._summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "_ContextManager":
        cm = cls(task=d["task"], fqbn=d["fqbn"])
        cm._turns   = d.get("_turns", [])
        cm._summary = d.get("_summary", [])
        return cm


# ── Checkpoint ────────────────────────────────────────────────────────────────

def _save_checkpoint(sess: _Session, ctx: _ContextManager, step: int):
    """Salva lo stato completo su disco — permette di riprendere da qui.
    Write atomico: scrive su .tmp poi rinomina per evitare checkpoint corrotti in caso di crash."""
    if sess.logger is None:
        return
    checkpoint = {
        "step":      step,
        "timestamp": datetime.now().isoformat(),
        "sess":      sess.to_dict(),
        "ctx":       ctx.to_dict(),
    }
    checkpoint_path = sess.logger.run_dir / "checkpoint.json"
    tmp_path = checkpoint_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(checkpoint_path)  # atomico sullo stesso filesystem


# ── Tool implementations ──────────────────────────────────────────────────────

_TOOLS_DIR = Path(__file__).parent.parent / "tools"


def _list_tools(args: dict, sess: _Session) -> dict:
    try:
        data = json.loads((_TOOLS_DIR / "lista.json").read_text())
        return {"tools": [{"nome": t["nome"], "scopo": t["scopo"]} for t in data["tools"]]}
    except Exception as e:
        return {"error": str(e)}


def _get_tool(args: dict, sess: _Session) -> dict:
    name = args.get("name", "")
    path = _TOOLS_DIR / f"{name}.json"
    if not path.exists():
        available = [p.stem for p in _TOOLS_DIR.glob("*.json") if p.stem != "lista"]
        return {"error": f"Tool '{name}' non trovato.", "available": available}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        return {"error": str(e)}


def _auto_enrich_task(sess: _Session) -> str:
    """Cerca lessons rilevanti nella KB e costruisce un testo di contesto
    da iniettare nel contesto di plan_task. Ritorna stringa vuota se niente."""
    try:
        from knowledge.semantic import search_lessons as sem_search_lessons
        lessons = sem_search_lessons(sess.task, n=5)
        if not lessons:
            from knowledge.db import search_lessons as db_search_lessons
            lessons = db_search_lessons(sess.task, limit=5)
        if not lessons:
            return ""

        # Filtra per distanza semantica (lessons vicine al task corrente)
        close = [l for l in lessons if l.get("distance") is None or l.get("distance", 1.0) < 0.8]
        if not close:
            close = lessons[:3]

        lines = ["=== LESSONS DA RUN PRECEDENTI (usa queste per arricchire il piano) ==="]
        for l in close:
            lines.append(f"[{l.get('task_type', 'general')}] {l.get('lesson', '')}")
            if l.get("spec_hint"):
                lines.append(f"  → specifica nella task desc: {l['spec_hint']}")
            if l.get("hardware_quirk"):
                lines.append(f"  → quirk hardware: {l['hardware_quirk']}")
        lines.append("======================================================================")

        enrichment = "\n".join(lines)
        if sess.logger:
            sess.logger.log(f"KB LESSONS ({len(close)}): {enrichment[:300]}")
        _dash("phase", name="KB LESSONS", detail=f"{len(close)} lezioni trovate")
        return enrichment
    except Exception:
        return ""


def _plan_task(args: dict, sess: _Session) -> dict:
    from agent.orchestrator import Orchestrator

    # Guard: se siamo già in una fase avanzata, restituiamo il piano già fatto
    # (evita che MI50 riesegua plan_task a vuoto dopo resume o in fase uploading/evaluating)
    _NEXT_TOOL = {
        _Session.PHASE_COMPILING:  "patch_code → compile",
        _Session.PHASE_UPLOADING:  "upload_and_read",
        _Session.PHASE_EVALUATING: "grab_frames → evaluate_visual",
        _Session.PHASE_DONE:       "save_to_kb → {done:true}",
    }
    if sess.phase not in (_Session.PHASE_PLANNING, _Session.PHASE_GENERATING):
        if sess.plan_result:
            next_hint = _NEXT_TOOL.get(sess.phase, "il tool appropriato per la fase corrente")
            return {
                "skipped": True,
                "reason": (
                    f"plan_task già eseguito. Fase corrente: {sess.phase}. "
                    f"Chiama ADESSO: {next_hint}. NON chiamare plan_task di nuovo."
                ),
                **{k: v for k, v in sess.plan_result.items()},
            }

    context = args.get("context", "")

    # Arricchisce il contesto con lessons dalla KB (salvate in sessione per plan_functions)
    if not sess.lessons_context:
        sess.lessons_context = _auto_enrich_task(sess)
    if sess.lessons_context:
        context = (context + "\n\n" + sess.lessons_context).strip()

    _phase("PLAN", "MI50 pianifica il task")
    orch = Orchestrator()
    plan = orch.plan_task(task=sess.task, context=context)
    result = {
        "approach":          plan["approach"],
        "libraries_needed":  plan["libraries_needed"],
        "key_points":        plan["key_points"],
        "vcap_frames":       plan["vcap_frames"],
    }
    # Salva piano per anchor generating + log
    sess.plan_result = result
    if sess.logger:
        sess.logger.save_json({"plan_task": result}, "plan")
        sess.logger.log(f"plan_task: {result['approach'][:80]}")
    return result


def _plan_functions(args: dict, sess: _Session) -> dict:
    from agent.orchestrator import Orchestrator
    from agent.notebook import Notebook
    # Guard: plan_functions già chiamata, non ripetere
    if sess.phase != _Session.PHASE_PLANNING:
        funcs = []
        if sess.nb:
            funcs = [f.get("nome", "?") for f in (sess.nb.funzioni or [])]
        return {
            "error": "plan_functions già eseguita. Piano completo.",
            "funzioni_pianificate": funcs,
            "prossimo_passo": "Chiama generate_globals con args:{} — il piano è pronto, M40 genera il codice.",
        }
    context = args.get("context", "")
    # Inietta lessons anche qui — è la chiamata più critica per la qualità del codice M40
    if sess.lessons_context:
        context = (context + "\n\n" + sess.lessons_context).strip()
    _phase("PLAN_FUNCS", "MI50 pianifica funzioni")
    orch = Orchestrator()
    result = orch.plan_functions(task=sess.task, context=context)
    sess.nb = Notebook(task=sess.task, board=sess.fqbn)
    sess.nb.set_funzioni(
        globals_hint=result.get("globals_hint", ""),
        funzioni=result.get("funzioni", []),
    )
    # Fase → generating: da qui il codice inizia a esistere
    sess.set_phase(_Session.PHASE_GENERATING)
    funcs = result.get("funzioni", [])
    if sess.logger:
        plan_data = json.loads((sess.logger.run_dir / "plan.json").read_text()) if \
                    (sess.logger.run_dir / "plan.json").exists() else {}
        plan_data["plan_functions"] = result
        sess.logger.save_json(plan_data, "plan")
        sess.logger.log(f"plan_functions: {len(funcs)} funzioni — {[f['nome'] for f in funcs]}")
    return {
        "globals_hint": result["globals_hint"],
        "funzioni": [{"nome": f["nome"], "firma": f["firma"], "compito": f["compito"]}
                     for f in funcs],
    }


def _auto_search_kb(sess: _Session) -> None:
    """Cerca un esempio simile nella KB e lo salva in sess.kb_example."""
    if sess.kb_example:
        return
    try:
        from knowledge.query_engine import search_snippets_text
        results = search_snippets_text(sess.task, limit=3)
        for r in results:
            code = r.get("code", "")
            if len(code) > 100 and r.get("board", "") == sess.fqbn:
                sess.kb_example = code[:1200]
                _dash("phase", name="KB HIT",
                      detail=f"Trovato esempio: {r.get('task_description','')[:60]}")
                if sess.logger:
                    sess.logger.log(f"KB HIT: {r.get('task_description','')[:60]}")
                return
        for r in results:
            code = r.get("code", "")
            if len(code) > 100:
                sess.kb_example = code[:1200]
                return
    except Exception:
        pass


def _generate_globals(args: dict, sess: _Session) -> dict:
    from agent.generator import Generator
    if sess.nb is None:
        return {"error": "Chiama plan_functions prima di generate_globals"}
    _auto_search_kb(sess)
    _phase("GLOBALS", "M40 genera globals")
    gen = Generator()
    result = gen.generate_globals(nb=sess.nb, kb_example=sess.kb_example)
    sess.nb.globals_code = result["code"]
    if result.get("thinking") and sess.logger:
        sess.logger.log(f"[THINK/M40/globals] {result['thinking'][:2000]}")
    return {"ok": True, "lines": len(result["code"].splitlines())}


def _generate_all_functions(args: dict, sess: _Session) -> dict:
    """Genera tutte le funzioni in parallelo usando M40."""
    from agent.generator import Generator
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if sess.nb is None:
        return {"error": "Chiama plan_functions prima di generate_all_functions"}

    funzioni = [f["nome"] for f in (sess.nb.funzioni or [])]
    if not funzioni:
        return {"error": "Nessuna funzione nel notebook. Chiama plan_functions prima."}

    _phase("GEN PARALLELO", f"M40 genera {len(funzioni)} funzioni in parallelo")
    _dash("phase", name="M40 PARALLEL", detail=f"{len(funzioni)} funzioni: {', '.join(funzioni)}")

    results = {}
    errors = {}

    def gen_one(nome):
        gen = Generator()
        return nome, gen.generate_function(nome=nome, nb=sess.nb, kb_example=sess.kb_example)

    with ThreadPoolExecutor(max_workers=min(len(funzioni), 4)) as pool:
        futures = {pool.submit(gen_one, nome): nome for nome in funzioni}
        for fut in as_completed(futures):
            nome = futures[fut]
            try:
                nome, result = fut.result()
                results[nome] = result["code"]
                if result.get("thinking") and sess.logger:
                    sess.logger.log(f"[THINK/M40/{nome}] {result['thinking'][:2000]}")
                _dash("func_done", nome=nome, righe=len(result["code"].splitlines()))
            except Exception as e:
                errors[nome] = str(e)

    # Retry automatico per funzioni fallite (timeout M40, connessione persa, ecc.)
    if errors:
        retry_names = list(errors.keys())
        if sess.logger:
            sess.logger.log(f"[RETRY] {len(retry_names)} funzioni fallite al primo tentativo: {retry_names}")
        errors_retry = {}
        with ThreadPoolExecutor(max_workers=min(len(retry_names), 2)) as pool:
            futures = {pool.submit(gen_one, nome): nome for nome in retry_names}
            for fut in as_completed(futures):
                nome = futures[fut]
                try:
                    nome, result = fut.result()
                    results[nome] = result["code"]
                    errors.pop(nome, None)  # rimosso dagli errori
                    if sess.logger:
                        sess.logger.log(f"[RETRY OK] {nome}: {len(result['code'].splitlines())} righe")
                    _dash("func_done", nome=nome, righe=len(result["code"].splitlines()))
                except Exception as e:
                    errors_retry[nome] = str(e)
        errors.update(errors_retry)

    for nome, code in results.items():
        sess.nb.update_funzione(nome, stato="done", codice=code)

    code, _ = sess.nb.assemble()
    sess.write_sketch(code)

    # Fase → compiling solo se tutte le funzioni sono state generate
    if errors:
        if sess.logger:
            sess.logger.log(f"[WARN] generate_all_functions: {len(errors)} funzioni non generate: {list(errors.keys())}")
        # Non avanzare a compiling — rimane in generating perché mancano funzioni
        return {
            "ok":      False,
            "generated": list(results.keys()),
            "errors":  errors,
            "missing": list(errors.keys()),
            "total_lines": len(code.splitlines()),
            "warning": f"Funzioni non generate (timeout M40): {list(errors.keys())}. Richiama generate_all_functions per ritentare.",
        }

    sess.set_phase(_Session.PHASE_COMPILING)
    if sess.logger:
        sess.logger.save_code(code, label="generated")
        sess.logger.log(f"generate_all_functions: {len(code.splitlines())} righe totali")

    # Rileva stub/codice incompleto nel codice generato
    _STUB_PATTERNS = [
        r"//\s*TODO", r"//\s*[Ii]mplement", r"//\s*[Aa]dd\s+logic",
        r"//\s*[Ii]nsert\s+code", r"//\s*[Ff]ill\s+in",
        r"//\s*[Pp]laceholder", r"//\s*[Ss]tub",
    ]
    stub_warnings = []
    for pat in _STUB_PATTERNS:
        matches = re.findall(pat, code)
        if matches:
            stub_warnings.append(f"{pat}: {len(matches)} occorrenze")
    if stub_warnings:
        if sess.logger:
            sess.logger.log(f"[WARN STUB] codice generato ha pattern incompleti: {stub_warnings}")
        return {
            "ok":          True,
            "generated":   list(results.keys()),
            "errors":      errors,
            "total_lines": len(code.splitlines()),
            "warning_stubs": f"Codice generato ha commenti stub/incompleti: {stub_warnings}. "
                             "Verifica che il codice sia completo prima di compilare.",
        }

    return {
        "ok":          True,
        "generated":   list(results.keys()),
        "errors":      errors,
        "total_lines": len(code.splitlines()),
    }


def _compile(args: dict, sess: _Session) -> dict:
    from agent.compiler import compile_sketch, fix_known_api_errors
    code_direct = args.get("code", "")
    if code_direct and not sess.code:
        sess.write_sketch(code_direct)
    if not sess.code:
        return {"error": "Nessun codice. Genera prima il codice con generate_all_functions."}
    sess.compile_attempts += 1
    _phase(f"COMPILE #{sess.compile_attempts}", "arduino-cli compila")
    if sess.compile_attempts > 1 and sess.errors:
        fixed = fix_known_api_errors(sess.code, sess.errors)
        if fixed != sess.code:
            sess.write_sketch(fixed)
    result = compile_sketch(str(sess.sketch_dir), fqbn=sess.fqbn)
    sess.errors = result.get("errors", [])
    _dash("compile_result", success=result["success"],
          errors=sess.errors[:5], attempt=sess.compile_attempts)

    if sess.logger:
        sess.logger.add_compile_errors(sess.compile_attempts, sess.errors)
        sess.logger.log(
            f"compile #{sess.compile_attempts}: {'OK' if result['success'] else f'{len(sess.errors)} errori'}"
        )

    if result["success"]:
        # Compila OK → fase uploading
        sess.set_phase(_Session.PHASE_UPLOADING)
    else:
        # Ancora errori → resta in compiling
        sess.set_phase(_Session.PHASE_COMPILING)

    return {
        "success":     result["success"],
        "errors":      sess.errors[:5],
        "error_count": len(sess.errors),
    }


def _analyze_errors(args: dict, sess: _Session) -> dict:
    from agent.orchestrator import Orchestrator
    errors = args.get("errors", sess.errors)
    if not errors:
        return {"error": "Nessun errore da analizzare"}
    _phase("ANALYZE", "MI50 analizza errori")
    orch = Orchestrator()
    result = orch.analyze_errors(code=sess.code, errors=errors)
    return {
        "analysis":  result["analysis"],
        "fix_hints": result.get("fix_hints", []),
    }


def _patch_code(args: dict, sess: _Session) -> dict:
    from agent.generator import Generator
    errors   = args.get("errors", sess.errors)
    analysis = args.get("analysis", "")
    _phase("PATCH", "M40 corregge il codice")
    gen = Generator()

    original_code = sess.code
    original_lines = len(original_code.splitlines())

    # Cerca lezioni KB rilevanti per gli errori di compilazione
    # e le inietta nel contesto del patcher M40
    kb_lessons_for_patch = ""
    try:
        error_text = " ".join(
            (e if isinstance(e, str) else e.get("message", ""))
            for e in (errors or [])
        )
        query = f"{sess.task[:80]} {error_text[:200]}"
        lessons = []
        try:
            from knowledge.semantic import search_lessons as sem_lessons
            lessons = sem_lessons(query, n=3)
        except Exception:
            pass
        if not lessons:
            # Fallback: keyword search in SQLite (trova anche lezioni non ancora in ChromaDB)
            from knowledge.db import search_lessons as db_lessons
            lessons = db_lessons(query, limit=3)
        if lessons:
            parts = [f"- {l.get('lesson', l.get('description', ''))}" for l in lessons[:3]]
            kb_lessons_for_patch = "\n".join(parts)
            if sess.logger:
                sess.logger.log(f"[PATCH] KB lessons iniettate ({len(lessons)}): {kb_lessons_for_patch[:200]}")
    except Exception:
        pass

    result = gen.patch_code(
        code=original_code, errors=errors, analysis=analysis,
        lessons=kb_lessons_for_patch,
    )
    patched_code = result["code"]
    patched_lines = len(patched_code.splitlines())

    # Rilevazione regressione: se il patch ha ridotto il codice di oltre il 40%
    # significa che M40 ha eliminato funzioni — scarta il patch e torna all'originale
    if patched_lines < original_lines * 0.6:
        if sess.logger:
            sess.logger.log(
                f"[PATCH REGRESSION] patch: {patched_lines} righe vs originale: {original_lines} righe "
                f"({patched_lines/original_lines*100:.0f}%) — patch scartato, ripristino originale"
            )
        # Non sovrascrivere il codice, resta sul codice originale
        sess.set_phase(_Session.PHASE_COMPILING)
        return {
            "ok": False,
            "lines": patched_lines,
            "warning": f"Patch scartato: regressione {original_lines}→{patched_lines} righe. "
                       "Il codice originale è stato ripristinato. Analizza gli errori più attentamente."
        }

    sess.write_sketch(patched_code)
    # Dopo il patch torniamo a compilare
    sess.set_phase(_Session.PHASE_COMPILING)
    if sess.logger:
        sess.logger.save_code(patched_code, label=f"patch{sess.compile_attempts}")
        sess.logger.log(f"patch_code: {patched_lines} righe (originale: {original_lines})")
        if result.get("thinking"):
            sess.logger.log(f"[THINK/M40/patch] {result['thinking'][:2000]}")
    return {"ok": True, "lines": patched_lines}


def _upload_and_read(args: dict, sess: _Session) -> dict:
    from agent.remote_uploader import upload_and_read_remote
    import subprocess
    serial_seconds = int(args.get("serial_seconds", 10))
    if not sess.code:
        return {"error": "Nessun codice da caricare"}

    # Limite retry: max 2 tentativi con stesso errore, poi kill processi Pi e riprova una volta
    MAX_RETRIES = 2
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        if attempt > 0:
            print(f"\n  [Upload] Tentativo {attempt+1}/{MAX_RETRIES+1} — "
                  f"kill processi bloccanti sul Pi...")
            try:
                subprocess.run(
                    ["sshpass", "-p", "pippopippo33$$", "ssh", "-o", "StrictHostKeyChecking=no",
                     "lele@192.168.1.167", "pkill -f esptool; pkill -f 'pio run'; sleep 2; echo done"],
                    capture_output=True, timeout=15
                )
            except Exception:
                pass

        _phase("UPLOAD", f"PlatformIO carica su ESP32 (tentativo {attempt+1})")
        result = upload_and_read_remote(
            ino_code=sess.code,
            task=sess.task,
            serial_duration=serial_seconds,
        )
        last_error = result.get("error")

        if result.get("success"):
            break  # successo → esci dal loop

        # Se stesso errore dopo 2 tentativi → fermati
        if attempt >= MAX_RETRIES:
            print(f"\n  [Upload] {MAX_RETRIES+1} tentativi falliti — errore: {last_error}")
            break

    sess.serial = result.get("serial_output", "")
    lines = [l for l in sess.serial.splitlines() if l.strip()]
    _dash("serial_output", lines=lines[:20])
    sess.set_phase(_Session.PHASE_EVALUATING)
    if sess.logger:
        (sess.logger.run_dir / "serial_output.txt").write_text(sess.serial, encoding="utf-8")
        sess.logger.log(f"upload: {'OK' if result.get('success') else 'FAIL'} | "
                        f"serial: {len(lines)} righe")
    return {
        "ok":            result.get("success", False),
        "serial_output": _serial_summary(sess.serial),
        "error":         last_error,
    }


def _grab_frames(args: dict, sess: _Session) -> dict:
    import time
    from agent.grab import grab_now
    n           = int(args.get("n_frames") or args.get("count") or args.get("n") or 3)
    interval_ms = int(args.get("interval_ms") or args.get("interval") or 1000)
    _phase("GRAB", f"webcam cattura {n} frame (attesa 5s boot ESP32...)")
    time.sleep(5)  # garantisce che ESP32 abbia finito il boot dopo upload
    result = grab_now(n_frames=n, interval_ms=interval_ms)
    if result.get("ok"):
        sess.frame_paths = result["frame_paths"]
        for idx, p in enumerate(sess.frame_paths):
            _frame(p, label="agent")
            if sess.logger:
                sess.logger.save_frame(p, idx=idx)
        if sess.logger:
            sess.logger.log(f"grab_frames: {len(sess.frame_paths)} frame salvati")
    return {
        "ok":          result.get("ok", False),
        "n_frames":    result.get("n_frames", 0),
        "frame_paths": result.get("frame_paths", []),
        "error":       result.get("error"),
    }


def _evaluate_visual(args: dict, sess: _Session) -> dict:
    from agent.evaluator import Evaluator
    frame_paths     = args.get("frame_paths", sess.frame_paths)
    serial          = args.get("serial_output", sess.serial)
    expected_events = args.get("expected_events", [])

    if not frame_paths:
        return {"error": "Nessun frame. Chiama grab_frames prima."}

    ev = Evaluator()

    # SERIAL-FIRST: se ci sono eventi attesi e serial output, verifica prima quello
    # È più affidabile e 10x più veloce di evaluate_visual
    if expected_events and serial and serial.strip():
        serial_check = ev.evaluate_serial_events(sess.task, serial, expected_events)
        if serial_check["success"]:
            _phase("EVAL SERIAL✓", "Serial output conferma funzionamento — skip valutazione visiva")
            result = {
                "success": True,
                "reason": serial_check["reason"],
                "suggestions": "",
                "pipeline": "serial-first",
            }
            if sess.logger:
                sess.logger.save_json(result, "result")
                sess.logger.log(f"evaluate: serial-first success — {result['reason'][:80]}")
            sess.set_phase(_Session.PHASE_DONE)
            return {"success": True, "reason": result["reason"], "suggestions": ""}

    # Pipeline opencv+m40 → fallback MI50-vision se necessario
    _phase("EVAL VISUAL", "pipeline opencv+M40 → fallback MI50-vision")
    result = ev.evaluate_visual_opencv(
        task=sess.task,
        frame_paths=frame_paths,
        serial_output=serial,
        expected_events=expected_events,
    )

    if sess.logger:
        sess.logger.save_json(result, "result")
        sess.logger.log(f"evaluate_visual: success={result['success']} "
                        f"pipeline={result.get('pipeline','?')} — {result['reason'][:80]}")
    sess.eval_result = {
        "success": result["success"],
        "reason": result["reason"],
        "pipeline": result.get("pipeline", "opencv+m40"),
    }
    sess.set_phase(_Session.PHASE_DONE)
    return {
        "success":     result["success"],
        "reason":      result["reason"],
        "suggestions": result.get("suggestions", ""),
    }


def _evaluate_text(args: dict, sess: _Session) -> dict:
    from agent.evaluator import Evaluator
    serial = args.get("serial_output", sess.serial)
    _phase("EVALUATE", "MI50 valuta output seriale")
    ev     = Evaluator()
    result = ev.evaluate(task=sess.task, serial_output=serial, code=sess.code)
    if sess.logger:
        sess.logger.save_json(result, "result")
        sess.logger.log(f"evaluate_text: success={result['success']} — {result['reason'][:80]}")
    sess.eval_result = {
        "success": result["success"],
        "reason": result["reason"],
        "pipeline": "evaluate_text",
    }
    sess.set_phase(_Session.PHASE_DONE)
    return {
        "success":     result["success"],
        "reason":      result["reason"],
        "suggestions": result["suggestions"],
    }


def _search_kb(args: dict, sess: _Session) -> dict:
    try:
        from knowledge.query_engine import search_snippets_text
        n       = int(args.get("n", 3))
        results = search_snippets_text(sess.task, limit=n)
        for r in results:
            if len(r.get("code", "")) > 400:
                r["code"] = r["code"][:400] + "\n..."
        return {"ok": True, "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _save_to_kb(args: dict, sess: _Session) -> dict:
    from agent.learner import Learner
    _phase("LEARN", "salva snippet nel DB")
    try:
        learner = Learner()
        # iterations: lista errori/fix dai cicli di compilazione (da logger._compile_errors)
        raw_iters = []
        if sess.logger and hasattr(sess.logger, "_compile_errors"):
            raw_iters = sess.logger._compile_errors
        iterations = [
            {"errors": e.get("errors", []), "fix": "patch_code"}
            for e in raw_iters
        ]
        learner.extract_patterns(
            task=sess.task,
            code=sess.code,
            iterations=iterations,
        )
        if sess.logger:
            sess.logger.log("save_to_kb: snippet salvato in KB")

        # Registra run nel memory server (best-effort, non blocca)
        try:
            import requests as _req
            _req.post(
                "http://127.0.0.1:7701/remember",
                json={
                    "project": "programmatore_di_arduini",
                    "text": f"Run completata ({__import__('datetime').date.today()}): task={sess.task!r}. Board={sess.fqbn}. Compile_cycles={len(iterations)+1}.",
                    "tags": ["run_completata", sess.fqbn.replace(":", "_")],
                },
                timeout=5,
            )
        except Exception:
            pass  # memory server non critico

        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Registry ──────────────────────────────────────────────────────────────────

_REGISTRY = {
    "list_tools":             _list_tools,
    "get_tool":               _get_tool,
    "search_kb":              _search_kb,
    "plan_task":              _plan_task,
    "plan_functions":         _plan_functions,
    "generate_globals":       _generate_globals,
    "generate_all_functions": _generate_all_functions,
    "compile":                _compile,
    "analyze_errors":         _analyze_errors,
    "patch_code":             _patch_code,
    "upload_and_read":        _upload_and_read,
    "grab_frames":            _grab_frames,
    "evaluate_visual":        _evaluate_visual,
    "evaluate_text":          _evaluate_text,
    "save_to_kb":             _save_to_kb,
}


def _execute(name: str, args: dict, sess: _Session) -> dict:
    fn = _REGISTRY.get(name)
    if fn is None:
        return {"error": f"Tool '{name}' non esiste.", "disponibili": list(_REGISTRY.keys())}
    try:
        return fn(args, sess)
    except Exception as e:
        import traceback
        return {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-300:]}


# ── JSON parsing ──────────────────────────────────────────────────────────────

def _parse(text: str) -> dict | None:
    clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    try:
        r = json.loads(clean)
        if isinstance(r, dict):
            return r
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", clean, re.DOTALL)
    if m:
        try:
            r = json.loads(m.group(1).strip())
            if isinstance(r, dict):
                return r
        except Exception:
            pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(clean):
        if ch == '{':
            try:
                obj, _ = decoder.raw_decode(clean, i)
                if isinstance(obj, dict) and ("tool" in obj or "done" in obj):
                    return obj
            except json.JSONDecodeError:
                pass
    return None


def _truncate_to_first_action(raw: str) -> str:
    """
    Tronca il testo di MI50 al primo JSON valido con 'tool' o 'done'.
    Previene che le fake continuazioni (run-ahead hallucination) inquinino il context.
    """
    think_m     = re.search(r"<think>(.*?)</think>", raw, re.DOTALL)
    think_block = think_m.group(0) if think_m else ""
    clean       = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    decoder     = json.JSONDecoder()
    for i, ch in enumerate(clean):
        if ch == '{':
            try:
                obj, end_pos = decoder.raw_decode(clean, i)
                if isinstance(obj, dict) and ("tool" in obj or "done" in obj):
                    action_str = clean[i:end_pos]
                    return (think_block + "\n\n" + action_str).strip()
            except json.JSONDecodeError:
                pass
    return raw


# ── Tool smoke test ───────────────────────────────────────────────────────────

def _smoke_test_tools(fqbn: str = "esp32:esp32:esp32") -> list[str]:
    """
    Smoke test reale di ogni tool: lo chiama con input minimali e verifica
    che risponda senza eccezioni e con il risultato atteso.

    NON fa upload (pericoloso) — testa solo la connettività SSH.
    Ritorna lista di errori (vuota = tutto OK).
    """
    import tempfile, os
    errors = []

    def _check(label: str, fn, *args, **kwargs):
        """Chiama fn, ritorna il risultato o registra l'errore."""
        try:
            r = fn(*args, **kwargs)
            return r
        except Exception as e:
            errors.append(f"[{label}] ERRORE: {type(e).__name__}: {e}")
            return None

    print("[Preflight] 1/7 compile_sketch — sketch minimale...", flush=True)
    from agent.compiler import compile_sketch
    import tempfile, os
    tmp = tempfile.mkdtemp(prefix="smoke_")
    sketch_name = os.path.basename(tmp)
    sketch_file = os.path.join(tmp, f"{sketch_name}.ino")
    open(sketch_file, "w").write("void setup(){} void loop(){}")
    r = _check("compile_sketch", compile_sketch, tmp, fqbn)
    if r is not None and "success" not in r:
        errors.append("[compile_sketch] risultato senza chiave 'success'")
    elif r is not None:
        print(f"  → compile: {'OK' if r['success'] else 'FAIL (atteso per sketch vuoto)'}", flush=True)
    shutil.rmtree(tmp, ignore_errors=True)

    print("[Preflight] 2/7 remote_uploader — SSH raggiungibile...", flush=True)
    from agent.remote_uploader import is_reachable
    r = _check("is_reachable", is_reachable)
    if r is False:
        errors.append("[is_reachable] Raspberry Pi non raggiungibile")
    elif r:
        print("  → Pi: raggiungibile", flush=True)

    print("[Preflight] 3/7 grab_now — cattura 1 frame...", flush=True)
    from agent.grab import grab_now
    r = _check("grab_now", grab_now, n_frames=1, interval_ms=500)
    if r is not None:
        if not r.get("ok"):
            errors.append(f"[grab_now] ok=False: {r.get('error')}")
        elif not r.get("frame_paths"):
            errors.append("[grab_now] frame_paths vuoto")
        else:
            _smoke_frame = r["frame_paths"][0]
            print(f"  → grab: {_smoke_frame}", flush=True)
    else:
        _smoke_frame = None

    print("[Preflight] 4/7 evaluate_text — MI50 health + import...", flush=True)
    # Verifica importazione e firma senza chiamare MI50 (risparmia 20 min di thinking)
    try:
        from agent.evaluator import Evaluator
        import inspect
        ev = Evaluator()
        sig_ev = inspect.signature(ev.evaluate)
        sig_vis = inspect.signature(ev.evaluate_visual)
        for param in ["task", "serial_output"]:
            if param not in sig_ev.parameters:
                errors.append(f"[evaluate_text] parametro mancante: {param}")
        for param in ["task", "frame_paths", "serial_output"]:
            if param not in sig_vis.parameters:
                errors.append(f"[evaluate_visual] parametro mancante: {param}")
        print(f"  → evaluate_text firma: OK", flush=True)
    except Exception as e:
        errors.append(f"[evaluate_text] import fallito: {e}")
        ev = None

    print("[Preflight] 5/7 evaluate_visual — torchvision nel container Docker...", flush=True)
    # Verifica torchvision con docker exec (istantaneo) invece di una chiamata MI50 completa
    import subprocess
    try:
        out = subprocess.run(
            ["docker", "exec", "mi50-server", "python3", "-c",
             "import torchvision; print('OK', torchvision.__version__)"],
            capture_output=True, text=True, timeout=10
        )
        if "OK" in out.stdout:
            print(f"  → torchvision: {out.stdout.strip()}", flush=True)
        else:
            errors.append(f"[evaluate_visual] torchvision non disponibile nel container: {out.stderr.strip()[:100]}")
    except Exception as e:
        errors.append(f"[evaluate_visual] docker exec fallito: {e}")

    print("[Preflight] 6/7 knowledge DB — scrivi e leggi snippet...", flush=True)
    from knowledge.db import add_snippet
    from knowledge.query_engine import search_snippets_text
    r = _check("add_snippet", add_snippet,
               task="__preflight_smoke_test__",
               code="void setup(){} void loop(){}",
               board=fqbn, tags=["preflight"])
    if r is not None:
        print(f"  → add_snippet: OK (id={r[:8]}...)", flush=True)
    r = _check("search_snippets_text", search_snippets_text, "preflight", 1)
    if r is not None:
        print(f"  → search_kb: {len(r)} risultati", flush=True)

    print("[Preflight] 7/7 save_to_kb (extract_patterns signature)...", flush=True)
    from agent.learner import Learner
    import inspect
    l = Learner()
    sig = inspect.signature(l.extract_patterns)
    expected = ["task", "code", "iterations"]
    actual = list(sig.parameters.keys())
    missing = [p for p in expected if p not in actual]
    if missing:
        errors.append(f"[extract_patterns] parametri mancanti: {missing} (firma attuale: {actual})")
    else:
        print(f"  → extract_patterns firma: OK {actual}", flush=True)

    return errors


# ── ReAct loop ────────────────────────────────────────────────────────────────

def _supervisor_pause(step: int, tool_name: str, result_str: str,
                       ctx: "_ContextManager", timeout: int = 60):
    """Pausa supervisore dopo ogni step. INVIO = continua, testo = nota a MI50."""
    import select
    print(f"\n{'─'*60}", flush=True)
    print(f"[SUPERVISORE] Step {step} — {tool_name} completato", flush=True)
    print(f"[SUPERVISORE] Risultato: {result_str[:200]}", flush=True)
    print(f"[SUPERVISORE] Nota (INVIO = salta, timeout {timeout}s): ", end="", flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if ready:
        note = sys.stdin.readline().strip()
        if note:
            supervisor_msg = (
                f"📋 NOTA SUPERVISORE dopo step {step} ({tool_name}): {note}\n"
                f"Tieni conto di questa indicazione nel prossimo passo."
            )
            ctx.add_turn(supervisor_msg, "_supervisor", "Nota presa in considerazione.")
            print(f"[SUPERVISORE] Nota registrata → MI50 la riceverà al prossimo step", flush=True)
        else:
            print("[SUPERVISORE] Continua →", flush=True)
    else:
        print(f"\n[SUPERVISORE] Timeout {timeout}s — continua automaticamente →", flush=True)
    print(f"{'─'*60}", flush=True)


def run(task: str, fqbn: str = "esp32:esp32:esp32", max_steps: int = 30,
        resume_dir: str = None, interactive: bool = False,
        supervisor_timeout: int = 60) -> dict:

    # ── Preflight smoke test ──────────────────────────────────────────────────
    print("\n[ToolAgent] ══ PREFLIGHT SMOKE TEST ══", flush=True)
    _dash("phase", name="PREFLIGHT", detail="verifica tool prima di iniziare")
    tool_errors = _smoke_test_tools(fqbn)
    if tool_errors:
        print("\n[ToolAgent] ❌ PREFLIGHT FALLITO — tool non funzionanti:", flush=True)
        for e in tool_errors:
            print(f"  {e}", flush=True)
        _dash("run_end", success=False, reason="Preflight failed: " + "; ".join(tool_errors))
        return {"success": False, "reason": "Tool preflight failed", "errors": tool_errors}
    print("[ToolAgent] ✅ Preflight OK — tutti i tool funzionanti\n", flush=True)
    _dash("phase", name="PREFLIGHT OK", detail="tutti i tool verificati")

    client = MI50Client.get()

    # ── Resume o nuova run ────────────────────────────────────────────────────
    if resume_dir:
        run_path   = Path(resume_dir)
        checkpoint = json.loads((run_path / "checkpoint.json").read_text())
        sess       = _Session.from_dict(checkpoint["sess"])
        ctx        = _ContextManager.from_dict(checkpoint["ctx"])
        start_step = checkpoint["step"] + 1
        logger     = RunLogger(sess.task, run_dir=run_path)
        sess.logger = logger
        logger.log(f"═══ RESUME da step {start_step} (fase: {sess.phase}) ═══")
        print(f"\n[ToolAgent] RESUME da {run_path} — riprendo da Step {start_step}", flush=True)
    else:
        sess        = _Session(task=task, fqbn=fqbn)
        ctx         = _ContextManager(task=task, fqbn=fqbn)
        start_step  = 1
        logger      = RunLogger(task)
        sess.logger = logger
        logger.save_json({"task": task, "fqbn": fqbn,
                          "start": datetime.now().isoformat()}, "meta")
        logger.log(f"═══ NUOVA RUN ═══")
        logger.log(f"TASK: {task}")
        logger.log(f"FQBN: {fqbn}")

    print(f"\n[ToolAgent] Run dir: {logger.run_dir}", flush=True)
    _dash("task_start", task=sess.task, board=sess.fqbn)
    _phase("AGENT START", f"tool agent avviato — {logger.run_dir.name}")

    retry_parse = 0
    _recent_tools: list[str] = []  # loop detection: ultimi tool chiamati

    for step in range(start_step, max_steps + 1):
        print(f"\n[ToolAgent] ── Step {step}/{max_steps} [fase: {sess.phase}] ──", flush=True)
        logger.log(f"── Step {step} [fase: {sess.phase}] ──")

        messages = ctx.build_messages(sess)
        result   = client.generate(messages, max_new_tokens=8192, label=f"MI50→Agent[{step}]")
        raw      = result["response"]
        if result.get("thinking"):
            logger.log(f"[THINK] {result['thinking'][:3000]}")
        print(f"[ToolAgent] MI50: {raw[:300]}", flush=True)

        parsed      = _parse(raw)
        raw_for_ctx = _truncate_to_first_action(raw)

        if parsed is None:
            retry_parse += 1
            if retry_parse > 2:
                reason = "Risposta non parsabile dopo 3 tentativi"
                logger.log(f"ABORT: {reason}")
                _dash("run_end", success=False, reason=reason)
                _finalize(sess, logger, success=False, reason=reason)
                return {"success": False, "reason": reason, "steps": step,
                        "run_dir": str(logger.run_dir)}
            ctx.add_turn(raw, "_parse_error",
                         'Risposta non parsabile. Rispondi SOLO con JSON: '
                         '{"tool":"nome","args":{},"reason":"..."} oppure {"done":true,...}')
            continue

        retry_parse = 0

        # ── Done ─────────────────────────────────────────────────────────────
        if parsed.get("done"):
            success = bool(parsed.get("success", False))
            reason  = parsed.get("reason", "")
            print(f"[ToolAgent] {'✅' if success else '❌'} {reason}", flush=True)
            _dash("run_end", success=success, reason=reason)
            _finalize(sess, logger, success=success, reason=reason)
            return {"success": success, "reason": reason, "steps": step,
                    "run_dir": str(logger.run_dir)}

        # ── Tool call ─────────────────────────────────────────────────────────
        tool_name   = parsed.get("tool", "")
        tool_args   = parsed.get("args") or {}
        tool_reason = parsed.get("reason", "")

        if not tool_name:
            ctx.add_turn(raw, "_no_tool", 'JSON senza "tool". Specifica il tool da chiamare.')
            continue

        print(f'[ToolAgent] 🔧 {tool_name}({list(tool_args.keys())}) — {tool_reason}', flush=True)
        logger.log(f"TOOL: {tool_name} | reason: {tool_reason[:60]}")

        tool_result = _execute(tool_name, tool_args, sess)

        # Rimuovi code e trace dal context (troppo lunghi)
        result_for_ctx = {k: v for k, v in tool_result.items() if k not in ("code", "trace")}
        result_str     = json.dumps(result_for_ctx, ensure_ascii=False)
        if len(result_str) > 1200:
            result_str = result_str[:1200] + "... (troncato)"

        print(f"[ToolAgent] Result: {result_str[:200]}", flush=True)
        logger.log(f"RESULT: {result_str[:200]}")

        # ── Loop detection ────────────────────────────────────────────────────
        _recent_tools.append(tool_name)
        if (len(_recent_tools) >= 3
                and len(set(_recent_tools[-3:])) == 1
                and _recent_tools[-1] not in ("_parse_error", "_no_tool")):
            loop_hint = (
                f"\n⚠ AVVISO SISTEMA: hai chiamato '{tool_name}' {3} volte consecutive "
                f"senza avanzare di fase. Devi cambiare approccio: "
                f"chiama un tool DIVERSO oppure chiudi con "
                f'{{\"done\": false, \"reason\": \"loop detected\", \"success\": false}}.'
            )
            result_str += loop_hint
            logger.log(f"LOOP DETECTED: {tool_name} × 3 — hint iniettato")
            _recent_tools.clear()  # reset dopo warning per non spammare

        ctx.add_turn(raw_for_ctx, tool_name, result_str)

        # Salva checkpoint dopo ogni tool completato
        _save_checkpoint(sess, ctx, step)

        # Pausa supervisore (solo se --interactive)
        if interactive:
            _supervisor_pause(step, tool_name, result_str, ctx,
                              timeout=supervisor_timeout)

    reason = f"Max steps ({max_steps}) raggiunto"
    _dash("run_end", success=False, reason=reason)
    _finalize(sess, logger, success=False, reason=reason)
    return {"success": False, "reason": reason, "steps": max_steps,
            "run_dir": str(logger.run_dir)}


def _finalize(sess: _Session, logger: RunLogger, success: bool, reason: str):
    """Pulizia finale: aggiorna meta.json e chiude il logger."""
    try:
        meta_path = logger.run_dir / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        meta.update({"end": datetime.now().isoformat(), "success": success, "reason": reason})
        logger.save_json(meta, "meta")
    except Exception:
        pass
    logger.close(success=success, reason=reason)
    sess.cleanup()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not _acquire_lock():
        pid = _LOCK_FILE.read_text().strip()
        print(f"\n❌ Tool Agent già in esecuzione (PID {pid}). Usa --resume o aspetta che finisca.", flush=True)
        print(f"   Per forzare: rm {_LOCK_FILE}", flush=True)
        sys.exit(1)

    import atexit
    atexit.register(_release_lock)

    parser = argparse.ArgumentParser(description="Tool Agent — agente ReAct per Arduino")
    parser.add_argument("task",      nargs="?", help="Task da eseguire (ometti se --resume)")
    parser.add_argument("--fqbn",    default="esp32:esp32:esp32")
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--resume",  help="Riprendi da una run precedente: path della run dir")
    parser.add_argument("--interactive", action="store_true",
                        help="Modalità supervisore: pausa dopo ogni step per input opzionale")
    parser.add_argument("--supervisor-timeout", type=int, default=60,
                        help="Secondi di attesa input supervisore (default: 60)")
    args = parser.parse_args()

    if args.resume:
        result = run(task="", fqbn=args.fqbn, max_steps=args.max_steps,
                     resume_dir=args.resume,
                     interactive=args.interactive,
                     supervisor_timeout=args.supervisor_timeout)
    elif args.task:
        result = run(args.task, fqbn=args.fqbn, max_steps=args.max_steps,
                     interactive=args.interactive,
                     supervisor_timeout=args.supervisor_timeout)
    else:
        parser.error("Specifica un task oppure usa --resume <run_dir>")

    print(f"\n{'='*50}")
    print(f"Risultato: {'✅ SUCCESSO' if result['success'] else '❌ FALLITO'}")
    print(f"Motivo: {result['reason']}")
    print(f"Steps: {result['steps']}")
    print(f"Run dir: {result.get('run_dir', 'N/A')}")
