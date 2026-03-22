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

Tool disponibili nell'observer:
  check_display_on    → display acceso? (white_ratio)
  capture_frames      → cattura N frame con timing interno
  detect_motion       → movimento tra frame (pixel diff + centroidi)
  count_objects       → blob detection (dot/segment/block + posizioni)
  view_frame          → MI50 vision guarda il frame raw e descrive cosa vede
  run_analysis        → riesegue blob detection con parametri custom (threshold, contrast)
  recalibrate         → ricalibra preset camera (calibrate_eye)
  read_text           → OCR via MI50 vision (solo se goal menziona testo)
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
    → {"on": bool, "white_ratio": float, "preset_used": str}
    Chiamalo SEMPRE PRIMA di tutto. Se on=false, ferma subito e riporta.
    Se white_ratio sembra basso ma il display dovrebbe essere acceso →
    chiama recalibrate() per trovare il preset camera migliore.

  capture_frames(n, interval_ms)
    → {"ok": bool, "frame_paths": [...], "n_frames": int}
    Cattura N frame a distanza fissa. Usa n=3, interval_ms=1000 per default.
    Se task richiede "animazione veloce": n=5, interval_ms=500.
    Se task richiede "verifica cambio stato": n=2, interval_ms=3000.

  detect_motion(frame_paths)
    → {"motion_detected": bool, "mean_diff": float, "centroid_displacement": float, "confidence": str}
    Richiede almeno 2 frame. Se confidence="low" ma ti aspetti movimento →
    chiama capture_frames di nuovo con interval_ms più lungo.

  count_objects(frame_paths)
    → {"total": int, "dots": [...], "segments": [...], "blocks": int, "description": str}
    dots=punti piccoli (≤16px), segments=forme medie (17-1500px).
    INTERPRETAZIONE BLOCKS (blob >1500px):
      - white_ratio < 0.02 e blocks=1: probabile riflesso ambientale → ignora.
      - white_ratio >= 0.02 e blocks=1: display con grafica densa → contenuto visivo.
      - blocks > 1 con motion_detected=true: quasi certamente oggetti in movimento.
    Se il risultato ti sembra strano → chiama run_analysis con parametri diversi
    oppure chiama view_frame per vedere il frame con i tuoi occhi.

  view_frame(frame_path)
    → {"description": str, "objects_seen": str, "confidence": str}
    MI50 vision guarda il frame raw e descrive liberamente cosa vede sul display.
    Usalo quando: count_objects dà risultati inattesi, white_ratio è anomalo,
    vuoi conferma visiva prima del report finale. LENTO (~30-60s).

  run_analysis(frame_paths, threshold, contrast)
    → {"total": int, "dots": [...], "segments": [...], "blocks": int, "description": str}
    Riesegue blob detection con parametri custom:
      threshold: int 0-255, soglia luminosità pixel (default 160)
        → abbassa se il display appare scuro (150, 120, 100)
        → alza se ci sono troppi falsi positivi (180, 200)
      contrast: float 1.0-5.0, boost contrasto PIL prima dell'analisi (default 1.0)
        → aumenta (2.0, 3.0) se il display è poco contrastato
    Usalo dopo count_objects se il risultato non sembra corretto.

  recalibrate()
    → {"preset": str, "scores": dict, "white_ratio_at_calibration": float}
    Prova tutti i preset camera (standard/dark/bright/oled_only/high_contrast)
    e salva il migliore. Usalo se: white_ratio è inaspettatamente basso,
    il display sembra presente ma non rilevato, dopo cambio setup fisico.
    Richiede ~10s (5 catture).

  read_text(frame_paths)
    → {"text_found": bool, "text": str, "confidence": str}
    LENTO (~60s). Usalo SOLO se goal menziona "testo", "score", "numero", "messaggio".

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
3. MAX 8 passi totali (incluso il report finale). Con view_frame/recalibrate usa
   i passi extra solo se davvero necessario.
4. Il report finale DEVE contenere success_hint: true/false rispetto al goal.
5. Se count_objects dà risultati strani, preferisci run_analysis o view_frame
   prima di concludere — non fidarti ciecamente dei numeri.
"""


# ── Tool implementations ───────────────────────────────────────────────────

def _tool_view_frame(frame_path: str) -> dict:
    """MI50 vision guarda il frame raw e descrive cosa vede."""
    try:
        from agent.mi50_client import MI50Client
    except ImportError:
        return {"error": "MI50 non disponibile", "description": "", "confidence": "low"}

    client = MI50Client()
    system = (
        "Sei un tecnico che analizza il display di un Arduino.\n"
        "Guarda l'immagine e descrivi in modo conciso e tecnico:\n"
        "1. Il display OLED è visibile? Dove si trova nell'immagine?\n"
        "2. Cosa mostra il display? (forme, punti, testo, pattern, niente)\n"
        "3. Quanti oggetti distinti vedi sul display?\n"
        "4. C'è qualcosa che potrebbe essere un riflesso ambientale (non sul display)?\n"
        "Rispondi in italiano, max 100 parole, sii preciso."
    )
    messages = [{"role": "user", "content": "Descrivi cosa vedi nell'immagine."}]

    try:
        raw = client.chat_with_image(
            messages=messages, image_path=frame_path,
            system=system, max_new_tokens=200, enable_thinking=False,
        )
        text = raw.strip() if isinstance(raw, str) else str(raw)
        return {
            "description": text,
            "objects_seen": text,
            "confidence": "medium",
        }
    except Exception as e:
        return {"error": str(e), "description": "", "confidence": "low"}


def _tool_run_analysis(frame_paths: list[str], threshold: int = 160, contrast: float = 1.0) -> dict:
    """Riesegue blob detection con threshold e contrast custom."""
    try:
        from PIL import Image, ImageEnhance
        import numpy as np
        from agent.occhio.analyze import _label_blobs
        from agent.occhio._common import THRESHOLD_OLED
    except ImportError as e:
        return {"error": str(e), "total": 0}

    if not frame_paths:
        return {"error": "Nessun frame", "total": 0}

    idx = len(frame_paths) // 2
    path = frame_paths[idx]

    try:
        img = Image.open(path).convert("L")

        # Applica boost contrasto se richiesto
        if contrast > 1.0:
            img = ImageEnhance.Contrast(img).enhance(contrast)

        arr_full = np.array(img)

        # Crop adattivo su pixel luminosi (usa threshold custom)
        bright_mask = arr_full > threshold
        bright_rows = np.where(bright_mask.any(axis=1))[0]
        bright_cols = np.where(bright_mask.any(axis=0))[0]
        if len(bright_rows) > 10 and len(bright_cols) > 10:
            pad = 20
            y0 = max(0, int(bright_rows.min()) - pad)
            y1 = min(arr_full.shape[0], int(bright_rows.max()) + pad)
            x0 = max(0, int(bright_cols.min()) - pad)
            x1 = min(arr_full.shape[1], int(bright_cols.max()) + pad)
            arr = arr_full[y0:y1, x0:x1]
        else:
            arr = arr_full

        binary = (arr > threshold).astype(np.uint8)
        labeled, n_labels = _label_blobs(binary)

        dots, segments, blocks = [], [], 0
        for label_id in range(1, n_labels + 1):
            ys, xs = np.where(labeled == label_id)
            if len(ys) == 0:
                continue
            area = len(ys)
            cx, cy = int(xs.mean()), int(ys.mean())
            if area <= 16:
                dots.append({"cx": cx, "cy": cy, "area": area})
            elif area <= 1500:
                segments.append({"cx": cx, "cy": cy, "area": area})
            else:
                blocks += 1

        total = len(dots) + len(segments)
        log(f"run_analysis(thr={threshold},ctr={contrast}): total={total} dots={len(dots)} segs={len(segments)} blocks={blocks}")
        return {
            "total": total, "dots": dots, "segments": segments, "blocks": blocks,
            "params_used": {"threshold": threshold, "contrast": contrast},
            "description": f"{total} oggetti (thr={threshold}, contrast={contrast})",
        }
    except Exception as e:
        return {"error": str(e), "total": 0}


def _tool_recalibrate() -> dict:
    """Ricalibra il preset camera ottimale."""
    from agent.occhio.calibrate import calibrate_eye
    return calibrate_eye(target="oled")


# ── Tool dispatcher ───────────────────────────────────────────────────────────

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

    elif tool_name == "view_frame":
        path = args.get("frame_path") or args.get("path") or (frame_paths[0] if frame_paths else None)
        if not path:
            return {"error": "Nessun frame disponibile. Chiama capture_frames prima."}
        log(f"  view_frame → MI50 vision su {path}")
        return _tool_view_frame(path)

    elif tool_name == "run_analysis":
        fp        = args.get("frame_paths", frame_paths)
        threshold = int(args.get("threshold", 160))
        contrast  = float(args.get("contrast", 1.0))
        if not fp:
            return {"error": "Nessun frame. Chiama capture_frames prima."}
        return _tool_run_analysis(fp, threshold=threshold, contrast=contrast)

    elif tool_name == "recalibrate":
        log("  recalibrate → calibrate_eye(oled)")
        return _tool_recalibrate()

    elif tool_name == "read_text":
        fp = args.get("frame_paths", frame_paths)
        if not fp:
            return {"error": "Nessun frame. Chiama capture_frames prima."}
        return read_text(fp)

    else:
        return {"error": f"Tool '{tool_name}' non disponibile per l'osservatore.",
                "disponibili": ["check_display_on", "capture_frames", "detect_motion",
                                "count_objects", "view_frame", "run_analysis",
                                "recalibrate", "read_text"]}


# ── JSON parser ────────────────────────────────────────────────────────────────

def _parse_m40_response(raw: str) -> dict | None:
    """Estrae l'oggetto JSON dalla risposta M40. Ritorna None se non trovato."""
    # Cerca JSON in blocchi markdown ```json ... ```
    m = re.search(r"```json\s*(.*?)```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass
    # Usa raw_decode per trovare JSON con "tool" o "done" (non sotto-oggetti vuoti)
    decoder = json.JSONDecoder()
    positions = [i for i, c in enumerate(raw) if c == "{"]
    best = None
    for pos in positions:
        try:
            obj, _ = decoder.raw_decode(raw, pos)
            if isinstance(obj, dict) and ("tool" in obj or "done" in obj):
                if best is None or len(obj) > len(best):
                    best = obj
        except (json.JSONDecodeError, ValueError):
            pass
    return best


def _m40_step(messages: list[dict]) -> str:
    """Chiama M40 per un singolo passo del mini-loop."""
    from agent.m40_client import M40Client
    client = M40Client()
    result = client.generate(messages, max_tokens=600, label="M40→Observer")
    return result.get("response", result.get("raw", ""))


# ── API pubblica ──────────────────────────────────────────────────────────────

def observe_display(goal: str, max_steps: int = 8) -> dict:
    """
    M40 assume temporaneamente il ruolo di agente osservatore visivo.

    Input:
        goal      : cosa deve osservare (es. "verifica che ci siano 5 boids in movimento")
        max_steps : massimo passi nel mini-loop (default 8, include report finale)
                    Passi extra rispetto a prima: view_frame e run_analysis possono
                    aggiungere 1-2 passi di approfondimento.

    Output (report strutturato per MI50):
        {
            "display_on":            bool,
            "objects_total":         int,
            "dots":                  list[{cx, cy, area}],
            "segments":              list[{cx, cy, area}],
            "motion_detected":       bool,
            "motion_confidence":     str,
            "centroid_displacement": float,
            "text":                  str,
            "description":           str,
            "success_hint":          bool,
            "reason":                str,
            "steps_taken":           int,
        }

    Dal punto di vista di MI50 questa è UNA SOLA tool call.
    Il contesto di MI50 non viene inquinato dai passi intermedi.
    """
    log(f"observe_display: goal='{goal[:80]}' max_steps={max_steps}")

    frame_paths: list[str] = []
    last_white_ratio: float = 0.0

    messages = [
        {"role": "system", "content": _OBSERVER_SYSTEM},
        {"role": "user",   "content": f"GOAL: {goal}\n\nInizia l'osservazione. Prima chiama check_display_on."},
    ]

    steps_taken = 0
    final_report = None

    for step in range(max_steps):
        steps_taken = step + 1
        log(f"  [Observer step {steps_taken}/{max_steps}]")

        try:
            raw = _m40_step(messages)
        except Exception as e:
            log(f"  M40 errore al passo {steps_taken}: {e}")
            break

        messages.append({"role": "assistant", "content": raw})

        parsed = _parse_m40_response(raw)
        if parsed is None:
            log(f"  passo {steps_taken}: risposta non parsata")
            messages.append({"role": "user", "content":
                "Risposta non valida. Rispondi SOLO con JSON: tool call o report finale."})
            continue

        if parsed.get("done"):
            final_report = parsed.get("report", parsed)
            log(f"  Observer completato al passo {steps_taken}: "
                f"success_hint={final_report.get('success_hint')}")
            break

        tool_name = parsed.get("tool", "")
        tool_args = parsed.get("args", {})

        if not tool_name:
            log(f"  passo {steps_taken}: nessun tool né done — termino")
            break

        log(f"  → {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:80]})")

        tool_result = _call_vision_tool(tool_name, tool_args, frame_paths)
        log(f"  ← {json.dumps(tool_result, ensure_ascii=False, default=str)[:150]}")

        if tool_name == "check_display_on":
            last_white_ratio = float(tool_result.get("white_ratio", 0.0))

        # Hint contestuale per count_objects con display denso
        extra = ""
        if tool_name == "count_objects" and last_white_ratio >= 0.02:
            extra = (f"\nNOTA: white_ratio={last_white_ratio:.3f} — "
                     f"i blocks sono probabilmente contenuto visivo (grafica densa), "
                     f"non riflessi ambientali.")

        result_msg = (
            f"Risultato {tool_name}:\n"
            f"{json.dumps(tool_result, ensure_ascii=False, default=str, indent=2)}"
            f"{extra}\n\n"
            f"Cosa fai adesso? Ricorda: max {max_steps - steps_taken} passi rimasti "
            f"(incluso il report finale). Se hai dubbi sui numeri usa view_frame o run_analysis."
        )
        messages.append({"role": "user", "content": result_msg})

    if final_report is None:
        log("  Observer: nessun report — fallback con dati parziali")
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
