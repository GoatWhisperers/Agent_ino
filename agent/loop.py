"""
Loop principale dell'agente Arduino.

Modalità:
  NEW     — task nuovo, cerca prima nel DB poi genera
  CONTINUE — riprende progetto esistente in workspace/current
  MODIFY  — modifica progetto funzionante con nuovi requisiti

Uso:
  python loop.py "fai lampeggiare un LED ogni 500ms" [--mode NEW|CONTINUE|MODIFY]
  python loop.py "fai lampeggiare un LED ogni 500ms" --no-upload  (solo compila, non carica)
"""

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agent.compiler import compile_sketch
from agent.uploader import find_arduino_port, upload_sketch, read_serial
from agent.remote_uploader import upload_and_read_remote, is_reachable, RPI_SERIAL_PORT
import agent.grab as grab
import agent.dashboard as dashboard
from agent.notebook import Notebook
from knowledge import db as kdb
from knowledge.query_engine import get_context_for_task, find_relevant_context

# ── Costanti ───────────────────────────────────────────────
MAX_COMPILE_ATTEMPTS = 5
MAX_EVAL_ATTEMPTS    = 3
SERIAL_READ_SECONDS  = 10

WORKSPACE_CURRENT   = ROOT / "workspace" / "current"
WORKSPACE_COMPLETED = ROOT / "workspace" / "completed"
LOGS_DIR            = ROOT / "logs"

# ── Logging strutturato ────────────────────────────────────

def _make_log_path() -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR / f"run_{ts}.jsonl"


def _write_event(log_fh, event: str, **data):
    """Scrive un evento JSONL nel file di log."""
    record = {
        "ts": datetime.utcnow().isoformat(),
        "event": event,
        **data,
    }
    log_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    log_fh.flush()


def _print(msg: str):
    print(msg, flush=True)


# ── Utility sketch ─────────────────────────────────────────

def _sketch_dir(name: str) -> Path:
    """Crea (o recupera) una directory sketch in workspace/current."""
    d = WORKSPACE_CURRENT / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_sketch(sketch_dir: Path, code: str) -> Path:
    """Scrive il codice in <sketch_dir>/<name>.ino e ritorna il path."""
    ino_path = sketch_dir / f"{sketch_dir.name}.ino"
    ino_path.write_text(code, encoding="utf-8")
    return ino_path


def _read_existing_sketch(sketch_dir: Path) -> str:
    """Legge il .ino nella directory, se esiste."""
    inos = list(sketch_dir.glob("*.ino"))
    if not inos:
        return ""
    return inos[0].read_text(encoding="utf-8", errors="replace")


def _save_completed(sketch_dir: Path, task: str):
    """Copia lo sketch in workspace/completed con timestamp."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_task = "".join(c if c.isalnum() or c in "_- " else "_" for c in task[:40]).strip()
    dest = WORKSPACE_COMPLETED / f"{ts}_{safe_task}"
    shutil.copytree(str(sketch_dir), str(dest))
    return dest


# ── Fase 0: Analyst ────────────────────────────────────────

def _phase_analyst(task: str, mode: str, sketch_dir: Path, log_fh) -> str:
    """
    Fase 0: cerca codice simile o analizza il progetto esistente.
    Ritorna stringa di contesto da passare al generatore.
    """
    _print("\n[FASE 0 — ANALYST]")
    context = ""

    if mode in ("CONTINUE", "MODIFY"):
        from agent.analyst import Analyst
        analyst = Analyst()

        if mode == "CONTINUE":
            _print("  Analisi progetto parziale...")
            state = analyst.analyze_project_state(str(sketch_dir))
            _write_event(log_fh, "analyst_project_state",
                         status=state["status"],
                         summary=state["summary"],
                         missing=state["missing"],
                         thinking=state["thinking"])
            context = (
                f"STATO DEL PROGETTO: {state['status']}\n"
                f"COSA FA: {state['summary']}\n"
                f"COSA MANCA: {state['missing']}\n\n"
                f"CODICE ESISTENTE:\n{state['code']}"
            )
            _print(f"  Stato: {state['status']} — {state['summary']}")

        else:  # MODIFY
            existing_code = _read_existing_sketch(sketch_dir)
            if existing_code:
                _print("  Analisi modifica richiesta...")
                analysis = analyst.analyze_for_modify(existing_code, task)
                _write_event(log_fh, "analyst_modify",
                             what_to_change=analysis["what_to_change"],
                             what_to_keep=analysis["what_to_keep"],
                             approach=analysis["approach"],
                             thinking=analysis["thinking"])
                context = (
                    f"CODICE ESISTENTE:\n{existing_code}\n\n"
                    f"COSA MODIFICARE: {analysis['what_to_change']}\n"
                    f"COSA MANTENERE: {analysis['what_to_keep']}\n"
                    f"APPROCCIO: {analysis['approach']}"
                )
                _print(f"  Modifica: {analysis['what_to_change'][:80]}...")
            else:
                _print("  MODIFY: nessun .ino trovato, parto da zero come NEW")

    else:  # NEW
        # Cerca codice simile nel DB
        ctx_text = get_context_for_task(task)
        relevant = find_relevant_context(task)
        has_snippets = len(relevant["snippets"]) > 0
        _write_event(log_fh, "analyst_search",
                     has_snippets=has_snippets,
                     n_snippets=len(relevant["snippets"]),
                     n_libraries=len(relevant["libraries"]))

        if has_snippets:
            from agent.analyst import Analyst
            analyst = Analyst()
            similar_codes = [
                {"description": s["task_description"], "code": s["code"]}
                for s in relevant["snippets"]
            ]
            _print(f"  Trovati {len(similar_codes)} snippet simili. Analisi...")
            analysis_text = analyst.analyze_similar_code(task, similar_codes)
            _write_event(log_fh, "analyst_similar_code", analysis=analysis_text)
            context = f"ANALISI CODICE SIMILE:\n{analysis_text}\n\n{ctx_text}"
            _print(f"  Analisi completata: {analysis_text[:80]}...")
        else:
            _print("  Nessun codice simile nel DB. Partenza da zero.")

    return context


# ── Fase 1-3: Planning ─────────────────────────────────────

def _phase_plan(task: str, context: str, mode: str, fqbn: str, log_fh) -> tuple[dict, Notebook]:
    """Fase 1: Orchestrator pianifica il task e inizializza il taccuino."""
    _print("\n[FASE 1 — ORCHESTRATOR: planning]")
    dashboard.phase("planning", "MI50 pianifica il task")
    from agent.orchestrator import Orchestrator
    orch = Orchestrator()
    plan = orch.plan_task(task, context=context, mode=mode)
    _write_event(log_fh, "orchestrator_plan",
                 approach=plan["approach"],
                 libraries=plan["libraries_needed"],
                 key_points=plan["key_points"],
                 note_tecniche=plan.get("note_tecniche", []),
                 thinking=plan["thinking"])
    _print(f"  Approccio: {plan['approach'][:100]}...")
    if plan["libraries_needed"]:
        _print(f"  Librerie: {', '.join(plan['libraries_needed'])}")

    # Inizializza il taccuino operativo
    nb = Notebook(task=task, board=fqbn)
    nb.set_plan(
        piano=plan["key_points"],
        dipendenze=plan["libraries_needed"],
        note_tecniche=plan.get("note_tecniche", []),
    )

    # Piano funzioni dettagliato
    _print("\n[FASE 1b — ORCHESTRATOR: piano funzioni]")
    dashboard.phase("func-plan", "MI50 pianifica le funzioni")
    func_plan = orch.plan_functions(task, context=context, mode=mode)
    _write_event(log_fh, "orchestrator_func_plan",
                 globals_hint=func_plan["globals_hint"],
                 n_funzioni=len(func_plan["funzioni"]),
                 funzioni=[f["nome"] for f in func_plan["funzioni"]],
                 thinking=func_plan["thinking"])

    if func_plan["funzioni"]:
        nb.set_funzioni(func_plan["globals_hint"], func_plan["funzioni"])
        _print(f"  Funzioni pianificate: {nb.progress()}")
    else:
        _print("  ⚠️  Piano funzioni vuoto — userò generazione monolitica")

    nb.update_stato("generating")
    _print(f"  Taccuino: {nb.summary()}")
    return plan, nb


# ── Fase 2: Code Generation ────────────────────────────────

def _phase_generate(task: str, nb: Notebook, plan: dict, log_fh) -> str:
    """
    Fase 2: M40 genera il codice funzione per funzione.
    Se il piano non ha funzioni (fallback), usa il vecchio metodo monolitico.
    """
    from agent.generator import Generator
    gen = Generator()

    if nb.funzioni:
        return _phase_generate_by_function(task, nb, plan, gen, log_fh)
    else:
        return _phase_generate_monolithic(task, nb, plan, gen, log_fh)


def _phase_generate_by_function(task: str, nb: Notebook, plan: dict, gen, log_fh) -> str:
    """Genera globals + ogni funzione separatamente, poi assembla."""
    _print("\n[FASE 2 — GENERATOR: generazione per funzione]")
    dashboard.phase("generate", "M40 genera funzione per funzione")

    # Step 2a: globals
    _print(f"  📦 Globals...")
    g = gen.generate_globals(nb)
    nb.globals_code = g["code"]
    _write_event(log_fh, "generator_globals", code_len=len(g["code"]))

    # Step 2b: funzioni in ordine di dipendenza
    ordine = nb.funzioni_ordinate()
    _print(f"  Ordine: {' → '.join(f['nome'] + '()' for f in ordine)}")

    for func in ordine:
        nome = func["nome"]
        nb.update_funzione(nome, "generating")
        _print(f"  🔧 {nome}()...")
        dashboard.func_start(nome)

        result = gen.generate_function(nome, nb)
        nb.update_funzione(nome, "done", result["code"])
        righe = result["code"].count("\n") + 1
        dashboard.func_done(nome, righe)
        dashboard.notebook_update(nb.summary(), nb.progress())
        _write_event(log_fh, f"generator_func_{nome}",
                     code_len=len(result["code"]),
                     thinking=result["thinking"])

    _print(f"\n  {nb.progress()}")

    # Assembla il .ino finale
    code, line_map = nb.assemble()
    _write_event(log_fh, "generator_assembled",
                 code_len=len(code),
                 n_funzioni=len(nb.funzioni))
    _print(f"  Sketch assemblato: {len(code)} caratteri, {len(nb.funzioni)+1} blocchi")
    return code


def _phase_generate_monolithic(task: str, nb: Notebook, plan: dict, gen, log_fh) -> str:
    """Fallback: genera tutto in una volta (vecchio comportamento)."""
    _print("\n[FASE 2 — GENERATOR: generazione monolitica]")
    result = gen.generate_code(
        task,
        context=nb.context_for_generator(),
        vcap_frames=plan.get("vcap_frames", 0),
        vcap_interval_ms=plan.get("vcap_interval_ms", 1000),
    )
    _write_event(log_fh, "generator_output",
                 code_len=len(result["code"]),
                 thinking=result["thinking"])
    _print(f"  Codice generato: {len(result['code'])} caratteri")
    return result["code"]


def _phase_patch(code: str, errors: list, error_analysis: dict, nb: Notebook, log_fh) -> str:
    """Fase 2b: M40 applica una patch al codice."""
    _print("\n[FASE 2b — PATCHER: correzione codice]")
    from agent.generator import Generator
    gen = Generator()
    result = gen.patch_code(
        code,
        errors,
        analysis=error_analysis.get("analysis", ""),
    )
    _write_event(log_fh, "patcher_output",
                 code_len=len(result["code"]),
                 thinking=result["thinking"])
    _print(f"  Codice corretto: {len(result['code'])} caratteri")

    # Aggiorna il taccuino con l'errore e il fix applicato
    if errors:
        primo_errore = errors[0].get("message", "")[:120]
        fix = error_analysis.get("analysis", "")[:120]
        nb.add_errore(primo_errore, fix)

    return result["code"]


# ── Fase 3: Compile + fix loop ─────────────────────────────

def _phase_compile_loop(
    code: str,
    sketch_dir: Path,
    plan: dict,
    fqbn: str,
    nb: Notebook,
    log_fh,
) -> tuple[bool, str, list]:
    """
    Ciclo compile → analyze → patch (max MAX_COMPILE_ATTEMPTS).
    Ritorna (success, final_code, iterations).
    """
    from agent.orchestrator import Orchestrator

    iterations = []
    current_code = code

    for attempt in range(1, MAX_COMPILE_ATTEMPTS + 1):
        _print(f"\n[FASE 3 — COMPILER: tentativo {attempt}/{MAX_COMPILE_ATTEMPTS}]")
        dashboard.phase("compile", f"tentativo {attempt}/{MAX_COMPILE_ATTEMPTS}")
        from agent.compiler import fix_known_includes
        current_code = fix_known_includes(current_code)
        _write_sketch(sketch_dir, current_code)
        result = compile_sketch(str(sketch_dir), fqbn=fqbn)

        _write_event(log_fh, "compile_attempt",
                     attempt=attempt,
                     success=result["success"],
                     errors=result["errors"],
                     warnings=result["warnings"])

        dashboard.compile_result(result["success"], result["errors"], attempt)

        if result["success"]:
            _print(f"  ✅ Compilazione OK")
            if result["warnings"]:
                _print(f"  ⚠️  {len(result['warnings'])} warning(s)")
            return True, current_code, iterations

        _print(f"  ❌ Errori: {len(result['errors'])}")
        for e in result["errors"][:3]:
            _print(f"     riga {e['line']}: {e['message']}")

        if attempt >= MAX_COMPILE_ATTEMPTS:
            _write_event(log_fh, "compile_max_attempts_reached")
            _print("  ❌ Massimo tentativi raggiunto.")
            return False, current_code, iterations

        # Analisi errori con MI50
        _print("\n[FASE 3a — ANALYZER: analisi errori]")
        orch = Orchestrator()
        error_analysis = orch.analyze_errors(current_code, result["errors"])
        _write_event(log_fh, "error_analysis",
                     analysis=error_analysis["analysis"],
                     hints=error_analysis["fix_hints"],
                     thinking=error_analysis["thinking"])
        _print(f"  Analisi: {error_analysis['analysis'][:120]}")

        # Patch con M40
        new_code = _phase_patch(current_code, result["errors"], error_analysis, nb, log_fh)
        iterations.append({
            "attempt": attempt,
            "errors": result["errors"],
            "analysis": error_analysis["analysis"],
            "fix": "patched",
        })
        current_code = new_code

    return False, current_code, iterations


# ── Fase 4: Upload + Serial ────────────────────────────────

def _phase_upload_serial(
    sketch_dir: Path,
    port: str,
    fqbn: str,
    baud: int,
    log_fh,
) -> dict:
    """Upload e lettura seriale. Ritorna {"serial_output": str, "error": str|None}."""
    _print(f"\n[FASE 4 — UPLOADER: upload su {port}]")

    # Trova il .hex che compile_sketch ha copiato accanto allo sketch
    hex_files = list(sketch_dir.glob("*.hex"))
    if not hex_files:
        _write_event(log_fh, "upload_no_hex")
        return {"serial_output": "", "error": "Nessun file .hex trovato dopo la compilazione"}

    hex_path = str(hex_files[0])
    upload_result = upload_sketch(hex_path, port, fqbn=fqbn)
    _write_event(log_fh, "upload_result",
                 success=upload_result["success"],
                 error=upload_result.get("error"))

    if not upload_result["success"]:
        _print(f"  ❌ Upload fallito: {upload_result['error']}")
        return {"serial_output": "", "error": upload_result["error"]}

    _print("  ✅ Upload OK. Lettura seriale...")
    time.sleep(1)  # attendi il boot della scheda

    serial_result = read_serial(port, baud=baud, duration_sec=SERIAL_READ_SECONDS)
    _write_event(log_fh, "serial_output",
                 output=serial_result["output"],
                 lines=serial_result["lines"],
                 error=serial_result.get("error"))
    _print(f"  Output seriale ({len(serial_result['lines'])} righe):")
    for line in serial_result["lines"][:10]:
        _print(f"    {line}")

    return {
        "serial_output": serial_result["output"],
        "error": serial_result.get("error"),
    }


# ── Fase 4b: Upload + Serial remoto (Raspberry Pi) ────────────────────────

def _phase_upload_serial_remote(
    task: str,
    sketch_dir: Path,
    plan: dict,
    baud: int,
    log_fh,
) -> dict:
    """
    Flusso remoto completo su Raspberry Pi:
      setup progetto PlatformIO → compile pio → upload pio → read serial (± camera)

    Se plan["vcap_frames"] > 0: usa flusso camera (avvia sessione prima dell'upload,
    raccoglie frame dopo). Altrimenti: usa read_serial_remote come prima.

    Ritorna:
        {
            "serial_output": str,
            "error": str | None,
            "frame_paths": list[str],   # vuoto se vcap_frames == 0
        }
    """
    from agent.remote_uploader import (
        setup_pio_project,
        compile_pio,
        upload_pio,
        read_serial_remote,
        RPI_SERIAL_PORT,
    )

    _print(f"\n[FASE 4 — RASPBERRY PI: setup progetto PlatformIO]")

    # Leggi il codice sorgente scritto nella workspace
    ino_files = list(sketch_dir.glob("*.ino"))
    if not ino_files:
        _write_event(log_fh, "upload_no_ino")
        return {"serial_output": "", "error": "Nessun file .ino trovato nella workspace",
                "frame_paths": []}

    ino_code = ino_files[0].read_text(encoding="utf-8", errors="replace")
    libraries = plan.get("libraries_needed", [])
    vcap_frames = plan.get("vcap_frames", 0)

    _print(f"  Sorgente: {ino_files[0].name} ({len(ino_code)} caratteri)")
    _print(f"  Librerie: {libraries or 'nessuna (built-in)'}")
    _print(f"  Porta remota: {RPI_SERIAL_PORT}")
    _print(f"  Visione: {'SI (vcap_frames=' + str(vcap_frames) + ')' if vcap_frames > 0 else 'NO'}")

    # ── Deploy grab_tool (sempre, costo minimo se già aggiornato) ───────────────
    if vcap_frames > 0:
        _print("  Deploy grab_tool.py sul Raspberry...")
        deploy_result = grab.deploy()
        _write_event(log_fh, "grab_deploy",
                     deployed=deploy_result.get("deployed"),
                     error=deploy_result.get("error"))
        if not deploy_result["ok"]:
            _print(f"  ⚠️  Deploy fallito: {deploy_result['error']} — continuo senza visione")
            vcap_frames = 0

    # ── Setup + compile PlatformIO (sempre necessario) ───────────────────────
    setup = setup_pio_project(task=task, ino_code=ino_code, libraries=libraries)
    if not setup["success"]:
        _write_event(log_fh, "remote_upload_result", success=False,
                     error=setup["error"], compile_stdout="", upload_stdout="")
        _print(f"  ❌ Setup progetto fallito: {setup['error']}")
        return {"serial_output": "", "error": f"Setup progetto fallito: {setup['error']}",
                "frame_paths": []}

    project_dir = setup["project_dir"]

    compile_result = compile_pio(project_dir)
    _write_event(log_fh, "remote_upload_result",
                 success=compile_result["success"],
                 error=None if compile_result["success"] else "Compilazione fallita",
                 compile_stdout=compile_result.get("stdout", "")[:1000],
                 upload_stdout="")

    if not compile_result["success"]:
        _print(f"  ❌ Compilazione PlatformIO fallita")
        return {"serial_output": "", "error": "Compilazione pio fallita sul Raspberry",
                "frame_paths": []}

    # ── Flusso con visione ──────────────────────────────────────────────────
    # NOTA: grab avviene DOPO upload per evitare conflitto su /dev/ttyUSB0.
    # La modalità serial grab apriva la porta prima dell'upload → porta occupata.
    # Ora: upload prima → attesa boot → grab_now immediato.
    if vcap_frames > 0:
        vcap_interval_ms = plan.get("vcap_interval_ms", 1000)

        # Kill processi residui pio/esptool sul Raspberry (porta occupata da run precedenti)
        from agent.remote_uploader import _ssh as _rpi_ssh
        _rpi_ssh("pkill -f esptool 2>/dev/null; pkill -f 'pio run' 2>/dev/null; true", timeout=5)

        # Upload firmware (porta libera, grab non ancora avviato)
        _print("  Upload firmware...")
        upload_result = upload_pio(project_dir, port=RPI_SERIAL_PORT)
        _write_event(log_fh, "upload_result",
                     success=upload_result["success"],
                     error=upload_result.get("error"))

        if not upload_result["success"]:
            _print(f"  ❌ Upload fallito: {upload_result['error']}")
            return {"serial_output": "", "error": f"Upload fallito: {upload_result['error']}",
                    "frame_paths": []}

        # Attesa boot ESP32 + lettura seriale iniziale
        _print("  Upload OK. Attendo boot ESP32 (3s)...")
        import time as _time
        _time.sleep(3)

        # Lettura breve seriale (output di setup)
        from agent.remote_uploader import _ssh as _rpi_ssh
        serial_lines = []
        try:
            r = _rpi_ssh(
                f"python3 -c \""
                f"import serial,time;"
                f"s=serial.Serial('{RPI_SERIAL_PORT}',{baud},timeout=0.3);"
                f"s.reset_input_buffer();"
                f"buf=b'';"
                f"[buf.__iadd__(s.read(256)) for _ in range(30)];"
                f"s.close();"
                f"print(''.join(chr(b) if 32<=b<127 or b in(10,13) else '' for b in buf))"
                f"\"",
                timeout=15,
            )
            raw = r.get("out", "")
            serial_lines = [l for l in raw.splitlines() if l.strip()]
        except Exception:
            pass

        serial_output = "\n".join(serial_lines)
        _print(f"  Seriale ({len(serial_lines)} righe):")
        for line in serial_lines[:10]:
            _print(f"    {line}")

        # Grab frame webcam in modalità immediata (porta già libera dopo upload)
        _print(f"  Cattura {vcap_frames} frame webcam...")
        grab_result = grab.grab_now(
            n_frames=vcap_frames,
            interval_ms=vcap_interval_ms,
        )
        _write_event(log_fh, "grab_collect",
                     n_frames=grab_result["n_frames"],
                     serial_lines=len(serial_lines),
                     error=grab_result.get("error"))

        if grab_result.get("error"):
            _print(f"  ⚠️  Errore cattura frame: {grab_result['error']}")

        _print(f"  Frame catturati: {grab_result['n_frames']}")

        _write_event(log_fh, "serial_output",
                     output=serial_output,
                     lines=serial_lines,
                     error=None,
                     frame_paths=grab_result["frame_paths"])

        return {
            "serial_output": serial_output,
            "error": grab_result.get("error"),
            "frame_paths": grab_result["frame_paths"],
        }

    # ── Flusso senza visione (originale) ─────────────────────────────────────
    # Kill processi residui pio/esptool sul Raspberry
    from agent.remote_uploader import _ssh as _rpi_ssh2
    _rpi_ssh2("pkill -f esptool 2>/dev/null; pkill -f 'pio run' 2>/dev/null; true", timeout=5)
    upload_result = upload_pio(project_dir, port=RPI_SERIAL_PORT)
    _write_event(log_fh, "upload_result",
                 success=upload_result["success"],
                 error=upload_result.get("error"))

    if not upload_result["success"]:
        _print(f"  ❌ Upload fallito: {upload_result['error']}")
        return {"serial_output": "", "error": f"Upload fallito: {upload_result['error']}",
                "frame_paths": []}

    _print("  ✅ Upload OK. Attendo boot ESP32...")
    import time as _time
    from agent.remote_uploader import _ssh as _rpi_ssh
    # Libera la porta da eventuali processi residui di pio/esptool
    _rpi_ssh("pkill -f 'esptool\\|pio\\|read_serial' 2>/dev/null; true", timeout=5)
    _time.sleep(5)  # attendi boot ESP32 (era 2s, troppo poco)
    serial_result = read_serial_remote(port=RPI_SERIAL_PORT, baud=baud,
                                       duration_sec=SERIAL_READ_SECONDS)

    _print("  Output seriale:")
    for line in serial_result["lines"][:10]:
        _print(f"    {line}")

    _write_event(log_fh, "serial_output",
                 output=serial_result["output"],
                 lines=serial_result["lines"],
                 error=serial_result.get("error"),
                 frame_paths=[])

    return {
        "serial_output": serial_result["output"],
        "error": serial_result.get("error"),
        "frame_paths": [],
    }


# ── Fase 5: Evaluation ────────────────────────────────────

def _phase_evaluate(task: str, serial_output: str, code: str, log_fh) -> dict:
    """MI50 valuta se il task è stato completato (solo testo/seriale)."""
    _print("\n[FASE 5 — EVALUATOR]")
    from agent.evaluator import Evaluator
    evaluator = Evaluator()
    result = evaluator.evaluate(task, serial_output, code=code)
    _write_event(log_fh, "evaluation",
                 success=result["success"],
                 reason=result["reason"],
                 suggestions=result["suggestions"],
                 thinking=result["thinking"])
    status = "✅ SUCCESSO" if result["success"] else "❌ NON RIUSCITO"
    _print(f"  {status}: {result['reason'][:120]}")
    if not result["success"] and result["suggestions"]:
        _print(f"  Suggerimenti: {result['suggestions'][:120]}")
    return result


def _phase_evaluate_visual(
    task: str,
    frame_paths: list,
    serial_output: str,
    code: str,
    log_fh,
) -> dict:
    """MI50 valuta visivamente il task usando frame catturati dalla webcam CSI."""
    _print(f"\n[FASE 5 — EVALUATOR VISIVO ({len(frame_paths)} frame)]")
    from agent.evaluator import Evaluator
    evaluator = Evaluator()
    result = evaluator.evaluate_visual(task, frame_paths, serial_output, code=code)
    _write_event(log_fh, "evaluation_visual",
                 success=result["success"],
                 reason=result["reason"],
                 suggestions=result["suggestions"],
                 thinking=result["thinking"],
                 n_frames=len(frame_paths))
    status = "✅ SUCCESSO (visivo)" if result["success"] else "❌ NON RIUSCITO (visivo)"
    _print(f"  {status}: {result['reason'][:120]}")
    if not result["success"] and result["suggestions"]:
        _print(f"  Suggerimenti: {result['suggestions'][:120]}")
    return result


# ── Fase 6: Learning ───────────────────────────────────────

def _phase_learn(task: str, code: str, iterations: list, fqbn: str, log_fh):
    """MI50 estrae pattern e aggiorna il DB."""
    _print("\n[FASE 6 — LEARNER]")
    from agent.learner import Learner
    learner = Learner()
    patterns = learner.extract_patterns(task, code, iterations)
    _write_event(log_fh, "learner_output",
                 snippet=patterns["snippet"],
                 libraries=patterns["libraries"],
                 error_fixes=patterns["error_fixes"],
                 thinking=patterns["thinking"])

    # Salva snippet nel DB (SQLite + ChromaDB)
    snippet_info = patterns["snippet"]
    tags = snippet_info.get("tags", [])
    libraries = [l["name"] for l in patterns["libraries"]]

    sid = kdb.add_snippet(
        task=task,
        code=code,
        board=fqbn,
        libraries=libraries,
        tags=tags,
    )
    _print(f"  Snippet salvato nel DB: {sid[:8]}... — tags: {tags}")

    # Indicizza nel ChromaDB
    from knowledge.semantic import index_snippet
    index_snippet(sid, task, code, tags)

    # Salva librerie
    for lib_info in patterns["libraries"]:
        name = lib_info.get("name", "")
        if name:
            kdb.add_library(
                name=name,
                description=lib_info.get("reason", ""),
                source="learned",
            )
            _print(f"  Libreria appresa: {name}")

    # Salva mappature errore→fix
    for ef in patterns["error_fixes"]:
        pattern = ef.get("pattern", "")
        fix = ef.get("fix", "")
        if pattern:
            kdb.add_error_fix(
                pattern=pattern,
                fix_description=fix,
            )
            _print(f"  Fix appreso: {pattern[:60]}")


# ── Main loop ──────────────────────────────────────────────

def run(
    task: str,
    mode: str = "NEW",
    fqbn: str = "arduino:avr:uno",
    baud: int = 9600,
    port: str = None,
    no_upload: bool = False,
    project_name: str = None,
):
    """
    Esegue il loop completo dell'agente.

    task       : descrizione in linguaggio naturale
    mode       : NEW | CONTINUE | MODIFY
    fqbn       : FQBN della scheda (default: arduino:avr:uno)
    baud       : baud rate seriale (default: 9600)
    port       : porta seriale (auto-detect se None)
    no_upload  : se True, si ferma dopo la compilazione
    project_name: nome cartella sketch (default: generato da task)
    """
    kdb.init_db()
    dashboard.start()
    dashboard.task_start(task, fqbn)

    log_path = _make_log_path()
    _print(f"\n{'='*60}")
    _print(f"AGENTE ARDUINO — {mode}")
    _print(f"Task: {task}")
    _print(f"Log: {log_path}")
    _print(f"{'='*60}")

    with open(log_path, "w", encoding="utf-8") as log_fh:
        _write_event(log_fh, "run_start",
                     task=task, mode=mode, fqbn=fqbn,
                     baud=baud, no_upload=no_upload)

        # Determina directory sketch
        if project_name is None:
            safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in task[:30]).strip("_")
            project_name = safe or "sketch"
        sketch_dir = _sketch_dir(project_name)
        _print(f"Workspace: {sketch_dir}")

        # ── Fase 0: Analyst ────────────────────────────────
        context = _phase_analyst(task, mode, sketch_dir, log_fh)

        # ── Fase 1: Planning + taccuino ────────────────────
        plan, nb = _phase_plan(task, context, mode, fqbn, log_fh)

        # ── Check librerie arduino-cli ─────────────────────────────────────────
        if plan["libraries_needed"]:
            from agent.compiler import check_libraries
            lib_check = check_libraries(plan["libraries_needed"])
            if not lib_check["all_ok"]:
                _print("\n⚠️  LIBRERIE MANCANTI — installa prima di continuare:")
                for lib in lib_check["missing"]:
                    _print(f"   arduino-cli lib install \"{lib}\"")
                _write_event(log_fh, "run_end", success=False, reason="missing_libraries",
                             missing=lib_check["missing"])
                dashboard.run_end(False, "missing_libraries")
                return {"success": False, "reason": "missing_libraries",
                        "missing": lib_check["missing"], "log": str(log_path)}

        # ── Fase 2: Generazione codice ─────────────────────
        code = _phase_generate(task, nb, plan, log_fh)

        # ── Fase 3: Compile + fix loop ─────────────────────
        nb.update_stato("compiling")
        compile_ok, final_code, iterations = _phase_compile_loop(
            code, sketch_dir, plan, fqbn, nb, log_fh
        )

        if not compile_ok:
            _print("\n❌ Compilazione fallita dopo tutti i tentativi.")
            nb.update_stato("failed")
            nb.save(sketch_dir / "notebook.json")
            kdb.add_run(task=task, mode=mode, success=False,
                        iterations=len(iterations), final_code=final_code)
            _write_event(log_fh, "run_end", success=False, reason="compile_failed")
            dashboard.run_end(False, "compile_failed")
            return {"success": False, "reason": "compile_failed", "log": str(log_path)}

        if no_upload:
            _print("\n✅ Compilazione OK. --no-upload: stop.")
            nb.update_stato("done")
            nb.save(sketch_dir / "notebook.json")
            kdb.add_run(task=task, mode=mode, success=True,
                        iterations=len(iterations), final_code=final_code)
            _write_event(log_fh, "run_end", success=True, reason="no_upload")
            dashboard.run_end(True, "no_upload")
            return {"success": True, "reason": "compiled_ok", "log": str(log_path)}

        # ── Rilevamento uploader: remoto (ESP32/Raspberry) o locale (AVR) ───────
        board_family = "esp32" if "esp32" in fqbn.lower() else "avr"
        use_remote = board_family == "esp32"

        if use_remote:
            _print("\n[AUTO-DETECT] ESP32 → uploader remoto via Raspberry Pi")
            if not is_reachable():
                _print("  ❌ Raspberry Pi non raggiungibile.")
                _write_event(log_fh, "run_end", success=False, reason="rpi_unreachable")
                kdb.add_run(task=task, mode=mode, success=False,
                            iterations=len(iterations), final_code=final_code)
                return {"success": False, "reason": "rpi_unreachable", "log": str(log_path)}
            _print(f"  Raspberry Pi raggiungibile. Porta: {RPI_SERIAL_PORT}")
        else:
            if port is None:
                _print("\n[AUTO-DETECT PORTA]")
                port = find_arduino_port()
                if port is None:
                    _print("  ❌ Nessuna scheda Arduino rilevata.")
                    _write_event(log_fh, "run_end", success=False, reason="no_board_found")
                    kdb.add_run(task=task, mode=mode, success=False,
                                iterations=len(iterations), final_code=final_code)
                    return {"success": False, "reason": "no_board_found", "log": str(log_path)}
                _print(f"  Porta rilevata: {port}")

        # ── Ciclo upload + evaluate ────────────────────────
        serial_output = ""
        eval_success = False
        eval_suggestions = ""

        for eval_attempt in range(1, MAX_EVAL_ATTEMPTS + 1):
            _print(f"\n[CICLO EVAL {eval_attempt}/{MAX_EVAL_ATTEMPTS}]")

            if eval_attempt > 1 and eval_suggestions:
                # Riscrivi il codice con i suggerimenti dell'evaluator (patch)
                _print("  Riscrittura codice in base ai suggerimenti...")
                rewrite_analysis = {"analysis": f"Suggerimenti dall'evaluator: {eval_suggestions}", "fix_hints": []}
                new_code = _phase_patch(final_code, [], rewrite_analysis, nb, log_fh)
                compile_ok2, final_code, new_iters = _phase_compile_loop(
                    new_code, sketch_dir, plan, fqbn, nb, log_fh
                )
                iterations.extend(new_iters)
                if not compile_ok2:
                    _print("  ❌ Riscrittura non compila, interrompo ciclo eval.")
                    break

            # Upload + lettura seriale (± frame visivi)
            if use_remote:
                upload_result = _phase_upload_serial_remote(
                    task, sketch_dir, plan, baud, log_fh
                )
            else:
                upload_result = _phase_upload_serial(sketch_dir, port, fqbn, baud, log_fh)
                upload_result["frame_paths"] = []

            if upload_result["error"] and not upload_result["serial_output"]:
                _print(f"  Upload/serial error: {upload_result['error']}")
                break

            serial_output = upload_result["serial_output"]
            frame_paths = upload_result.get("frame_paths", [])

            # Notifica dashboard
            if serial_output.strip():
                dashboard.serial_output(serial_output.splitlines()[:20])
            for fp in frame_paths:
                dashboard.frame(fp, label=f"frame {frame_paths.index(fp)+1}")

            # Controllo output vuoto: se il seriale non ha prodotto nulla di leggibile,
            # non ha senso chiamare l'Evaluator — segna come non valutabile e break.
            if not serial_output.strip() and not frame_paths:
                _print("  ⚠️  Output seriale vuoto o solo garbage — skip evaluation.")
                _write_event(log_fh, "evaluation_skipped",
                             reason="empty_serial_output",
                             eval_attempt=eval_attempt)
                eval_suggestions = "Il codice deve stampare output leggibile via Serial. Assicurati di chiamare Serial.begin(115200) e Serial.println() con messaggi significativi."
                continue

            # Valutazione: visiva se ci sono frame, altrimenti testuale
            if frame_paths:
                eval_result = _phase_evaluate_visual(
                    task, frame_paths, serial_output, final_code, log_fh
                )
            else:
                eval_result = _phase_evaluate(task, serial_output, final_code, log_fh)

            if eval_result["success"]:
                eval_success = True
                break
            eval_suggestions = eval_result.get("suggestions", "")

        # ── Fase 6: Learning (solo se successo) ────────────
        if eval_success:
            nb.update_stato("done")
            nb.save(sketch_dir / "notebook.json")
            _phase_learn(task, final_code, iterations, fqbn, log_fh)
            dest = _save_completed(sketch_dir, task)
            _print(f"\n  Progetto salvato in: {dest}")

        # ── Salva run nel DB ───────────────────────────────
        kdb.add_run(
            task=task,
            mode=mode,
            success=eval_success,
            iterations=len(iterations),
            final_code=final_code,
            serial_output=serial_output,
        )
        _write_event(log_fh, "run_end",
                     success=eval_success,
                     iterations=len(iterations))

        dashboard.run_end(eval_success, "done" if eval_success else "eval_failed")
        outcome = "✅ TASK COMPLETATO" if eval_success else "⚠️ TASK NON COMPLETATO"
        _print(f"\n{'='*60}")
        _print(outcome)
        _print(f"Log: {log_path}")
        _print(f"{'='*60}\n")

        return {
            "success": eval_success,
            "log": str(log_path),
            "final_code": final_code,
        }


# ── CLI ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Agente autonomo programmatore Arduino")
    parser.add_argument("task", help="Descrizione del task in linguaggio naturale")
    parser.add_argument("--mode", choices=["NEW", "CONTINUE", "MODIFY"], default="NEW")
    parser.add_argument("--fqbn", default="arduino:avr:uno",
                        help="FQBN della scheda (default: arduino:avr:uno)")
    parser.add_argument("--port", default=None,
                        help="Porta seriale (auto-detect se non specificata)")
    parser.add_argument("--baud", type=int, default=None,
                        help="Baud rate seriale (default: 115200 per ESP32, 9600 per AVR)")
    parser.add_argument("--project", default=None,
                        help="Nome progetto (cartella in workspace/current)")
    parser.add_argument("--no-upload", action="store_true",
                        help="Compila solo, non caricare sulla scheda")
    args = parser.parse_args()

    # Baud rate auto: 115200 per ESP32, 9600 per AVR
    baud = args.baud
    if baud is None:
        baud = 115200 if "esp32" in args.fqbn.lower() else 9600

    result = run(
        task=args.task,
        mode=args.mode,
        fqbn=args.fqbn,
        baud=baud,
        port=args.port,
        no_upload=args.no_upload,
        project_name=args.project,
    )
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
