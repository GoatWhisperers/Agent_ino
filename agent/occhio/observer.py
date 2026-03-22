"""
observer.py — M40 come agente osservatore visivo (sub-agent pattern).

observe_display(goal, max_steps) → dict

  M40 assume temporaneamente il ruolo di "osservatore visivo":
  - riceve goal (cosa deve osservare)
  - esegue un mini ReAct loop con i vision tool
  - riporta un resoconto strutturato
  - ritorna il controllo a MI50 con UN SOLO risultato

  Dal punto di vista di MI50, è una singola tool call.
  M40 non vede il contesto principale di MI50 — il suo context è isolato.

Flusso tipico che M40-observer esegue autonomamente:
  check_display_on  →  display acceso?
  capture_frames    →  cattura N frame
  detect_motion     →  c'è movimento?
  count_objects     →  quanti oggetti e dove?
  [read_text]       →  opzionale, solo se goal menziona testo/score
  → report          →  {"objects": ..., "motion": ..., "success_hint": bool, ...}
"""

import json
import re
import sys
from agent.occhio._common import log

# ── System prompt per M40-Observer ───────────────────────────────────────────

_OBSERVER_SYSTEM = """\
Sei un agente osservatore visivo per display OLED Arduino.
Il tuo UNICO compito è osservare il display e riportare cosa vedi.

HAI ACCESSO A QUESTI TOOL (chiamali in sequenza, uno alla volta):

  check_display_on()
    → {"on": bool, "white_ratio": float}
    Chiamalo SEMPRE PRIMA di tutto. Se on=false, ferma subito e riporta.

  capture_frames(n, interval_ms)
    → {"ok": bool, "frame_paths": [...], "n_frames": int}
    Cattura N frame a distanza fissa. Usa n=3, interval_ms=1000 per default.
    Se il task richiede "animazione veloce": n=5, interval_ms=500.
    Se il task richiede "verifica cambio stato": n=2, interval_ms=3000.

  detect_motion(frame_paths)
    → {"motion_detected": bool, "mean_diff": float, "centroid_displacement": float, "confidence": str}
    Richiede almeno 2 frame. Chiamalo DOPO capture_frames.

  count_objects(frame_paths)
    → {"total": int, "dots": [...], "segments": [...], "blocks": int, "description": str}
    Conta e localizza oggetti. dots=punti piccoli, segments=forme medie, blocks=artefatti(ignora).

  read_text(frame_paths)
    → {"text_found": bool, "text": str, "confidence": str}
    LENTO (~60s). Usalo SOLO se il goal menziona esplicitamente "testo", "score", "numero", "messaggio".

FORMATO RISPOSTA (scegli UNO per turno):

  Tool call:
  {"tool": "nome_tool", "args": {...}, "reason": "perché lo chiamo"}

  Report finale (quando hai abbastanza info):
  {"done": true, "report": {
    "display_on": bool,
    "objects_total": int,
    "dots": [...],
    "segments": [...],
    "motion_detected": bool,
    "motion_confidence": str,
    "centroid_displacement": float,
    "text": str,
    "description": str,
    "success_hint": bool,
    "reason": "spiegazione concisa (max 100 parole)"
  }}

REGOLE:
1. UNA SOLA azione per risposta. Aspetta il risultato prima di procedere.
2. NON inventare risultati. Se check_display_on ritorna on=false, fermati.
3. MAX 6 passi totali (incluso il report finale).
4. Il report finale DEVE contenere success_hint: true/false rispetto al goal.
5. NON chiamare gli stessi tool due volte a meno che non sia strettamente necessario.
"""


# ── Mini ReAct loop per M40-Observer ─────────────────────────────────────────

def _call_vision_tool(tool_name: str, args: dict, frame_paths: list[str]) -> dict:
    """
    Esegue un vision tool. frame_paths è lo stato condiviso tra i tool.
    Ritorna il risultato del tool.
    """
    from agent.occhio.capture import capture_frames, check_display_on
    from agent.occhio.analyze import detect_motion, count_objects
    from agent.occhio.read import read_text

    if tool_name == "check_display_on":
        return check_display_on()

    elif tool_name == "capture_frames":
        n           = int(args.get("n") or args.get("n_frames") or 3)
        interval_ms = int(args.get("interval_ms") or args.get("interval") or 1000)
        result = capture_frames(n=n, interval_ms=interval_ms)
        frame_paths.clear()
        frame_paths.extend(result)
        return {"ok": len(result) > 0, "frame_paths": result, "n_frames": len(result)}

    elif tool_name == "detect_motion":
        fp = args.get("frame_paths", frame_paths)
        if not fp:
            return {"error": "Nessun frame. Chiama capture_frames prima."}
        return detect_motion(fp)

    elif tool_name == "count_objects":
        fp = args.get("frame_paths", frame_paths)
        if not fp:
            return {"error": "Nessun frame. Chiama capture_frames prima."}
        return count_objects(fp)

    elif tool_name == "read_text":
        fp = args.get("frame_paths", frame_paths)
        if not fp:
            return {"error": "Nessun frame. Chiama capture_frames prima."}
        return read_text(fp)

    else:
        return {"error": f"Tool '{tool_name}' non disponibile per l'osservatore."}


def _parse_m40_response(raw: str) -> dict | None:
    """Estrae l'oggetto JSON dalla risposta M40. Ritorna None se non trovato."""
    # Cerca JSON in blocchi markdown ```json ... ```
    m = re.search(r"```json\s*(.*?)```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass
    # Cerca JSON libero (dal più lungo al più corto)
    for m in reversed(list(re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", raw, re.DOTALL))):
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _m40_step(messages: list[dict]) -> str:
    """Chiama M40 per un singolo passo del mini-loop."""
    from agent.m40_client import M40Client
    client = M40Client()
    result = client.generate(messages, max_tokens=300, label="M40→Observer")
    return result.get("response", result.get("raw", ""))


# ── API pubblica ──────────────────────────────────────────────────────────────

def observe_display(goal: str, max_steps: int = 6) -> dict:
    """
    M40 assume temporaneamente il ruolo di agente osservatore visivo.

    Input:
        goal      : cosa deve osservare (es. "verifica che ci siano 5 boids in movimento")
        max_steps : massimo passi nel mini-loop (default 6, include report finale)

    Output (report strutturato per MI50):
        {
            "display_on":           bool,
            "objects_total":        int,
            "dots":                 list[{cx, cy, area}],
            "segments":             list[{cx, cy, area}],
            "motion_detected":      bool,
            "motion_confidence":    str,
            "centroid_displacement": float,
            "text":                 str,
            "description":          str,
            "success_hint":         bool,
            "reason":               str,
            "steps_taken":          int,
        }

    Dal punto di vista di MI50 questa è UNA SOLA tool call.
    Il contesto di MI50 non viene inquinato dai passi intermedi.
    """
    log(f"observe_display: goal='{goal[:80]}...' max_steps={max_steps}")

    # Stato condiviso tra i tool del mini-loop
    frame_paths: list[str] = []

    # Contesto M40-Observer (isolato dal contesto principale MI50)
    messages = [
        {"role": "system", "content": _OBSERVER_SYSTEM},
        {"role": "user",   "content": f"GOAL: {goal}\n\nInizia l'osservazione. Prima chiama check_display_on."},
    ]

    steps_taken = 0
    final_report = None

    for step in range(max_steps):
        steps_taken = step + 1
        log(f"  [Observer step {steps_taken}/{max_steps}]")

        # Chiama M40
        try:
            raw = _m40_step(messages)
        except Exception as e:
            log(f"  M40 errore al passo {steps_taken}: {e}")
            break

        # Aggiungi risposta M40 al contesto
        messages.append({"role": "assistant", "content": raw})

        # Parse risposta
        parsed = _parse_m40_response(raw)
        if parsed is None:
            log(f"  passo {steps_taken}: risposta non parsata, termino")
            messages.append({"role": "user", "content":
                "Risposta non valida. Rispondi SOLO con JSON: tool call o report finale."})
            continue

        # Report finale?
        if parsed.get("done"):
            final_report = parsed.get("report", parsed)
            log(f"  Observer completato al passo {steps_taken}: "
                f"success_hint={final_report.get('success_hint')}")
            break

        # Tool call
        tool_name = parsed.get("tool", "")
        tool_args = parsed.get("args", {})
        reason    = parsed.get("reason", "")

        if not tool_name:
            log(f"  passo {steps_taken}: nessun tool né done — termino")
            break

        log(f"  → {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:80]})")

        # Esegui il tool
        tool_result = _call_vision_tool(tool_name, tool_args, frame_paths)
        log(f"  ← {json.dumps(tool_result, ensure_ascii=False, default=str)[:120]}")

        # Aggiungi risultato al contesto M40-Observer
        result_msg = (
            f"Risultato {tool_name}:\n"
            f"{json.dumps(tool_result, ensure_ascii=False, default=str, indent=2)}\n\n"
            f"Cosa fai adesso? Ricorda: max {max_steps - steps_taken} passi rimasti "
            f"(incluso il report finale)."
        )
        messages.append({"role": "user", "content": result_msg})

    # Se M40 non ha prodotto un report → fallback con dati raccolti
    if final_report is None:
        log("  Observer: nessun report prodotto — fallback con dati parziali")
        final_report = {
            "display_on":            None,
            "objects_total":         0,
            "dots":                  [],
            "segments":              [],
            "motion_detected":       False,
            "motion_confidence":     "low",
            "centroid_displacement": 0.0,
            "text":                  "",
            "description":           "Osservazione incompleta (M40 non ha prodotto report)",
            "success_hint":          False,
            "reason":                "Observer non ha completato l'osservazione",
        }

    final_report["steps_taken"] = steps_taken
    return final_report
