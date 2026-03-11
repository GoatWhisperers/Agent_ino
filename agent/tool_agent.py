"""
Tool Agent — agente ReAct che usa MI50 per decidere quali tools chiamare.

Il modello vede il task, ragiona, e chiama tools in sequenza.
I tools sono eseguiti dal loop Python e il risultato torna al modello.

Lo stato corrente (codice, notebook) è gestito server-side: il modello
non porta il codice in conversazione, solo i risultati sintetici.

Avvio:
    python agent/tool_agent.py "task" [--fqbn esp32:esp32:esp32] [--max-steps 30]
"""

import argparse
import json
import re
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.mi50_client import MI50Client
import agent.dashboard as dashboard

_ROOT = Path(__file__).parent.parent
_TOOLS_DIR = _ROOT / "tools"

# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM = """Sei un agente autonomo che programma Arduino/ESP32.
Completa il task assegnato chiamando tools in sequenza, un passo alla volta.

HARDWARE:
- ESP32 NodeMCU, FQBN: esp32:esp32:esp32
- Display OLED SSD1306 128x64, I2C SDA=GPIO21 SCL=GPIO22, addr=0x3C
- Webcam CSI su Raspberry Pi — usala se il task ha display/LED visibili

FORMATO RISPOSTA — SEMPRE uno di questi due JSON puri, zero testo fuori:
  Chiama tool:   {"tool":"nome","args":{...},"reason":"perché"}
  Task finito:   {"done":true,"success":bool,"reason":"spiegazione"}

TOOLS SEMPRE DISPONIBILI (senza list_tools):
  list_tools              → lista tools con descrizione 1 riga
  get_tool(name)          → schema completo di un tool

FLUSSO TIPICO:
  1. plan_task            → approccio, librerie, vcap_frames
  2. plan_functions       → lista funzioni da generare
  3. generate_globals     → sezione #include/#define/variabili
  4. generate_function    → genera ogni funzione (ripeti per ognuna)
  5. compile              → compila; se errori → analyze_errors → patch → compile
  6. upload_and_read      → carica ESP32, legge seriale
  7. grab_frames          → cattura webcam SE task ha display (usa vcap_frames dal piano)
  8. evaluate_text        → valuta con output seriale
     evaluate_visual      → valuta con frame (se hai catturato)
  9. save_to_kb           → salva se success=true
 10. {"done":true,...}

Rispondi SOLO con JSON valido. Nessun testo aggiuntivo."""

# ── Stato sessione (server-side) ───────────────────────────────────────────────

class _Session:
    """Stato corrente della sessione: codice, notebook, frame, serial."""
    def __init__(self, task: str, fqbn: str):
        self.task = task
        self.fqbn = fqbn
        self.nb = None          # Notebook corrente
        self.sketch_dir = None  # Path directory sketch
        self.code = ""          # Codice corrente assemblato
        self.errors = []        # Ultimi errori compilatore
        self.serial = ""        # Output seriale
        self.frame_paths = []   # Path frame webcam
        self.compile_attempts = 0

    def write_sketch(self, code: str):
        """Scrive il codice nella directory sketch."""
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

# ── Tool implementations ───────────────────────────────────────────────────────

def _list_tools(args: dict, sess: _Session) -> dict:
    try:
        data = json.loads((_TOOLS_DIR / "lista.json").read_text())
        # Ritorna solo nome + scopo per non gonfiare il contesto
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


def _plan_task(args: dict, sess: _Session) -> dict:
    from agent.orchestrator import Orchestrator
    context = args.get("context", "")
    dashboard.phase("PLAN", "orchestrator pianifica il task")
    orch = Orchestrator()
    plan = orch.plan_task(task=sess.task, context=context)
    return {
        "approach": plan["approach"],
        "libraries_needed": plan["libraries_needed"],
        "key_points": plan["key_points"],
        "vcap_frames": plan["vcap_frames"],
        "vcap_interval_ms": plan["vcap_interval_ms"],
    }


def _plan_functions(args: dict, sess: _Session) -> dict:
    from agent.orchestrator import Orchestrator
    from agent.notebook import Notebook
    context = args.get("context", "")
    dashboard.phase("PLAN_FUNCS", "orchestrator pianifica funzioni")
    orch = Orchestrator()
    result = orch.plan_functions(task=sess.task, context=context)
    # Crea notebook
    sess.nb = Notebook(task=sess.task, board=sess.fqbn)
    sess.nb.set_funzioni(
        globals_hint=result.get("globals_hint", ""),
        funzioni=result.get("funzioni", []),
    )
    return {
        "globals_hint": result["globals_hint"],
        "funzioni": [{"nome": f["nome"], "firma": f["firma"], "compito": f["compito"]}
                     for f in result["funzioni"]],
    }


def _generate_globals(args: dict, sess: _Session) -> dict:
    from agent.generator import Generator
    if sess.nb is None:
        return {"error": "Chiama plan_functions prima di generate_globals"}
    dashboard.phase("GLOBALS", "M40 genera globals")
    gen = Generator()
    result = gen.generate_globals(nb=sess.nb)
    sess.nb.globals_code = result["code"]
    return {"ok": True, "lines": len(result["code"].splitlines())}


def _generate_function(args: dict, sess: _Session) -> dict:
    from agent.generator import Generator
    if sess.nb is None:
        return {"error": "Chiama plan_functions prima di generate_function"}
    nome = args.get("nome", "")
    if not nome:
        return {"error": "Specifica args.nome"}
    dashboard.phase(f"GEN {nome}()", "M40 genera funzione")
    dashboard.func_start(nome)
    gen = Generator()
    result = gen.generate_function(nome=nome, nb=sess.nb)
    sess.nb.update_funzione(nome, stato="done", codice=result["code"])
    lines = len(result["code"].splitlines())
    dashboard.func_done(nome, lines)
    # Assembla e scrivi sketch aggiornato
    code, _ = sess.nb.assemble()
    sess.write_sketch(code)
    return {"ok": True, "nome": nome, "lines": lines}


def _compile(args: dict, sess: _Session) -> dict:
    from agent.compiler import compile_sketch, fix_known_api_errors
    if not sess.code:
        return {"error": "Nessun codice da compilare. Genera prima il codice."}
    sess.compile_attempts += 1
    dashboard.phase(f"COMPILE #{sess.compile_attempts}", "arduino-cli compila")
    # Fix API errors noti dal tentativo precedente
    if sess.compile_attempts > 1 and sess.errors:
        fixed = fix_known_api_errors(sess.code, sess.errors)
        if fixed != sess.code:
            sess.write_sketch(fixed)
    result = compile_sketch(str(sess.sketch_dir), fqbn=sess.fqbn)
    sess.errors = result.get("errors", [])
    dashboard.compile_result(result["success"], sess.errors, attempt=sess.compile_attempts)
    return {
        "success": result["success"],
        "errors": sess.errors[:5],
        "error_count": len(sess.errors),
    }


def _analyze_errors(args: dict, sess: _Session) -> dict:
    from agent.orchestrator import Orchestrator
    errors = args.get("errors", sess.errors)
    if not errors:
        return {"error": "Nessun errore da analizzare"}
    dashboard.phase("ANALYZE", "MI50 analizza errori")
    orch = Orchestrator()
    result = orch.analyze_errors(code=sess.code, errors=errors)
    return {
        "analysis": result["analysis"],
        "fix_hints": result.get("fix_hints", []),
    }


def _patch_code(args: dict, sess: _Session) -> dict:
    from agent.generator import Generator
    errors = args.get("errors", sess.errors)
    analysis = args.get("analysis", "")
    dashboard.phase("PATCH", "M40 corregge il codice")
    gen = Generator()
    result = gen.patch_code(code=sess.code, errors=errors, analysis=analysis)
    sess.write_sketch(result["code"])
    return {"ok": True, "lines": len(result["code"].splitlines())}


def _upload_and_read(args: dict, sess: _Session) -> dict:
    from agent.remote_uploader import upload_and_read_remote
    serial_seconds = int(args.get("serial_seconds", 10))
    if not sess.code:
        return {"error": "Nessun codice da caricare"}
    dashboard.phase("UPLOAD", "PlatformIO carica su ESP32")
    result = upload_and_read_remote(
        ino_code=sess.code,
        task=sess.task,
        fqbn=sess.fqbn,
        serial_seconds=serial_seconds,
    )
    sess.serial = result.get("serial_output", "")
    lines = [l for l in sess.serial.splitlines() if l.strip()]
    dashboard.serial_output(lines[:20])
    return {
        "ok": result.get("upload_ok", False),
        "serial_output": sess.serial[:400],
        "error": result.get("error"),
    }


def _grab_frames(args: dict, sess: _Session) -> dict:
    from agent.grab import grab_now
    n = int(args.get("n_frames", 3))
    interval_ms = int(args.get("interval_ms", 1000))
    dashboard.phase("GRAB", f"webcam cattura {n} frame")
    result = grab_now(n_frames=n, interval_ms=interval_ms)
    if result.get("ok"):
        sess.frame_paths = result["frame_paths"]
        for p in sess.frame_paths:
            dashboard.frame(p, label="agent")
    return {
        "ok": result.get("ok", False),
        "n_frames": result.get("n_frames", 0),
        "frame_paths": result.get("frame_paths", []),
        "error": result.get("error"),
    }


def _evaluate_text(args: dict, sess: _Session) -> dict:
    from agent.evaluator import Evaluator
    serial = args.get("serial_output", sess.serial)
    dashboard.phase("EVALUATE", "MI50 valuta output seriale")
    ev = Evaluator()
    result = ev.evaluate(task=sess.task, serial_output=serial, code=sess.code)
    return {
        "success": result["success"],
        "reason": result["reason"],
        "suggestions": result["suggestions"],
    }


def _evaluate_visual(args: dict, sess: _Session) -> dict:
    from agent.evaluator import Evaluator
    frame_paths = args.get("frame_paths", sess.frame_paths)
    serial = args.get("serial_output", sess.serial)
    if not frame_paths:
        return {"error": "Nessun frame disponibile. Chiama grab_frames prima."}
    dashboard.phase("EVAL VISUAL", "MI50 valuta frame webcam")
    ev = Evaluator()
    result = ev.evaluate_visual(task=sess.task, frame_paths=frame_paths, serial_output=serial)
    return {
        "success": result["success"],
        "reason": result["reason"],
        "suggestions": result["suggestions"],
    }


def _search_kb(args: dict, sess: _Session) -> dict:
    try:
        from knowledge.query_engine import QueryEngine
        qe = QueryEngine()
        n = int(args.get("n", 3))
        results = qe.search_snippets_text(sess.task, n_results=n)
        # Trunca codice
        for r in results:
            if len(r.get("code", "")) > 400:
                r["code"] = r["code"][:400] + "\n..."
        return {"ok": True, "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _save_to_kb(args: dict, sess: _Session) -> dict:
    from agent.learner import Learner
    notes = args.get("notes", "")
    dashboard.phase("LEARN", "salva snippet nel DB")
    try:
        learner = Learner()
        learner.extract_patterns(
            task=sess.task,
            code=sess.code,
            board=sess.fqbn,
            notes=notes,
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Registry ───────────────────────────────────────────────────────────────────

_REGISTRY = {
    "list_tools":       _list_tools,
    "get_tool":         _get_tool,
    "search_kb":        _search_kb,
    "plan_task":        _plan_task,
    "plan_functions":   _plan_functions,
    "generate_globals": _generate_globals,
    "generate_function":_generate_function,
    "compile":          _compile,
    "analyze_errors":   _analyze_errors,
    "patch_code":       _patch_code,
    "upload_and_read":  _upload_and_read,
    "grab_frames":      _grab_frames,
    "evaluate_text":    _evaluate_text,
    "evaluate_visual":  _evaluate_visual,
    "save_to_kb":       _save_to_kb,
}


def _execute(name: str, args: dict, sess: _Session) -> dict:
    fn = _REGISTRY.get(name)
    if fn is None:
        avail = list(_REGISTRY.keys())
        return {"error": f"Tool '{name}' non esiste.", "disponibili": avail}
    try:
        return fn(args, sess)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ── JSON parsing ───────────────────────────────────────────────────────────────

def _parse(text: str) -> dict | None:
    # JSON diretto
    try:
        return json.loads(text.strip())
    except Exception:
        pass
    # Markdown code block
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    # Cerca il primo oggetto JSON con tool o done
    for m in reversed(list(re.finditer(r"\{[\s\S]*?\}", text))):
        try:
            r = json.loads(m.group(0))
            if isinstance(r, dict) and ("tool" in r or "done" in r):
                return r
        except Exception:
            pass
    return None


# ── ReAct loop ─────────────────────────────────────────────────────────────────

def run(task: str, fqbn: str = "esp32:esp32:esp32", max_steps: int = 30) -> dict:
    client = MI50Client.get()
    sess = _Session(task=task, fqbn=fqbn)

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Task: {task}\nFQBN: {fqbn}"},
    ]

    dashboard.task_start(task, fqbn)
    dashboard.phase("AGENT START", "tool agent avviato")
    print(f"\n[ToolAgent] Task: {task}", flush=True)

    retry_parse = 0

    for step in range(1, max_steps + 1):
        print(f"\n[ToolAgent] ── Step {step}/{max_steps} ──", flush=True)

        result = client.generate(messages, max_new_tokens=512, label=f"MI50→Agent[{step}]")
        raw = result["response"]
        print(f"[ToolAgent] MI50: {raw[:300]}", flush=True)

        parsed = _parse(raw)

        if parsed is None:
            retry_parse += 1
            if retry_parse > 2:
                dashboard.run_end(False, "Risposta non parsabile dopo 3 tentativi")
                sess.cleanup()
                return {"success": False, "reason": "Risposta non parsabile", "steps": step}
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content":
                'Rispondi SOLO con JSON: {"tool":"nome","args":{...},"reason":"..."} '
                'oppure {"done":true,"success":bool,"reason":"..."}'})
            continue

        retry_parse = 0

        # ── Done ──
        if parsed.get("done"):
            success = bool(parsed.get("success", False))
            reason = parsed.get("reason", "")
            print(f"[ToolAgent] {'✅' if success else '❌'} {reason}", flush=True)
            dashboard.run_end(success, reason)
            sess.cleanup()
            return {"success": success, "reason": reason, "steps": step}

        # ── Tool call ──
        tool_name = parsed.get("tool", "")
        tool_args = parsed.get("args") or {}
        tool_reason = parsed.get("reason", "")

        if not tool_name:
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": 'Specifica "tool" nel JSON.'})
            continue

        print(f"[ToolAgent] 🔧 {tool_name}({list(tool_args.keys())}) — {tool_reason}", flush=True)

        tool_result = _execute(tool_name, tool_args, sess)

        # Serializza risultato — tronca parti grandi
        result_for_ctx = dict(tool_result)
        if "code" in result_for_ctx:
            del result_for_ctx["code"]  # il codice non va in conversazione
        result_str = json.dumps(result_for_ctx, ensure_ascii=False)
        if len(result_str) > 1500:
            result_str = result_str[:1500] + "... (troncato)"

        print(f"[ToolAgent] Result: {result_str[:200]}", flush=True)

        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content":
            f"Risultato {tool_name}:\n{result_str}"})

    dashboard.run_end(False, f"Max {max_steps} step raggiunto")
    sess.cleanup()
    return {"success": False, "reason": f"Max steps ({max_steps}) raggiunto", "steps": max_steps}


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tool Agent — agente ReAct per Arduino")
    parser.add_argument("task", help="Task da eseguire")
    parser.add_argument("--fqbn", default="esp32:esp32:esp32")
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--no-dashboard", action="store_true")
    args = parser.parse_args()

    if not args.no_dashboard:
        dashboard.start()

    result = run(args.task, fqbn=args.fqbn, max_steps=args.max_steps)
    print(f"\n{'='*50}")
    print(f"Risultato: {'✅ SUCCESSO' if result['success'] else '❌ FALLITO'}")
    print(f"Motivo: {result['reason']}")
    print(f"Steps: {result['steps']}")
