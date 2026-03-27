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
import threading
from agent.occhio._common import log

# ── System prompt per M40-Observer ───────────────────────────────────────────

_OBSERVER_SYSTEM = """\
Sei un agente osservatore OLED. Rispondi SOLO con JSON valido.

TOOL disponibili:
  check_display_on() → {on, white_ratio}
  capture_frames(n, interval_ms) → {ok, frame_paths, n_frames}
  detect_motion(frame_paths) → {motion_detected, mean_diff, centroid_displacement, confidence}
  count_objects(frame_paths) → {total, dots, segments, blocks}
  view_frame(frame_path) → {description} [MI50 vision — già in esecuzione in parallelo]
  run_analysis(frame_paths, threshold, contrast) → {total, dots, segments, blocks}
  recalibrate() → {preset}
  read_text(frame_paths) → {text_found, text}

SEQUENZA: check_display_on → capture_frames → view_frame → detect_motion → count_objects → report

FORMATO tool call:
{"tool": "nome", "args": {}, "reason": "perché"}

FORMATO report finale:
{"done": true, "report": {"display_on": bool, "objects_total": int, "dots": [], "segments": [], "motion_detected": bool, "motion_confidence": str, "centroid_displacement": float, "text": null, "description": str, "success_hint": bool, "reason": str}}

REGOLE: 1 azione/turno. NON inventare risultati. Max 8 passi. success_hint rispetto al goal.
Se display OFF → stop immediato. Blocks >1500px = riflesso se white_ratio<0.02.
"""


# ── Tool implementations ───────────────────────────────────────────────────

_VISION_STAGING = "/mnt/raid0/observer_frames"

def _tool_view_frame(frame_path: str) -> dict:
    """MI50 vision guarda il frame raw e descrive cosa vede."""
    import shutil, os, time
    try:
        from agent.mi50_client import MI50Client
    except ImportError:
        return {"error": "MI50 non disponibile", "description": "", "confidence": "low"}

    # MI50 gira in Docker — monta solo /mnt/raid0.
    # Prepariamo il frame: crop sul display + boost contrasto → più facile per il modello.
    os.makedirs(_VISION_STAGING, exist_ok=True)
    staged = os.path.join(_VISION_STAGING, f"frame_{int(time.time()*1000)}.jpg")
    try:
        from PIL import Image as _PIL_Image, ImageEnhance as _PILEnh
        import numpy as _np
        from agent.occhio._common import THRESHOLD_OLED
        _img = _PIL_Image.open(frame_path).convert("L")
        _arr = _np.array(_img)
        # Crop adattivo sulla bbox luminosa
        _mask = _arr > THRESHOLD_OLED
        _rows = _np.where(_mask.any(axis=1))[0]
        _cols = _np.where(_mask.any(axis=0))[0]
        if len(_rows) > 10 and len(_cols) > 10:
            pad = 30
            y0 = max(0, int(_rows.min()) - pad)
            y1 = min(_arr.shape[0], int(_rows.max()) + pad)
            x0 = max(0, int(_cols.min()) - pad)
            x1 = min(_arr.shape[1], int(_cols.max()) + pad)
            _img = _img.crop((x0, y0, x1, y1))
        # Boost contrasto ×3 e converti RGB per MI50
        _img = _PILEnh.Contrast(_img).enhance(3.0)
        _img = _img.convert("RGB")
        _img.save(staged, quality=95)
    except Exception:
        # fallback: copia il frame originale
        try:
            shutil.copy2(frame_path, staged)
        except Exception as e:
            return {"error": f"copy frame fallita: {e}", "description": "", "confidence": "low"}

    client = MI50Client()
    messages = [
        {
            "role": "user",
            "content": (
                "Questa è una foto di un display OLED 128×64 pixel collegato a un Arduino/ESP32, "
                "ripresa da una webcam in ambiente buio. Il display OLED appare come una zona "
                "rettangolare con pixel bianchi luminosi su sfondo nero. Le zone rosse o colorate "
                "ai bordi sono riflessi ambientali, non il display.\n\n"
                "Descrivi in italiano, max 3 frasi:\n"
                "1. Quante forme luminose bianche distinte vedi (cerchi, punti, rettangoli)?\n"
                "2. Le forme si muovono o sono statiche (confronta zone di sfocatura)?\n"
                "3. C'è del testo leggibile sul display?\n"
                "NON descrivere caratteri o simboli testuali per le forme geometriche."
            ),
        }
    ]

    try:
        result = client.generate_with_images(
            messages=messages,
            image_paths=[staged],
            max_new_tokens=200,
            label="Observer→MI50vision",
        )
        text = result.get("response", result.get("raw", "")).strip()
        return {
            "description": text,
            "objects_seen": text,
            "confidence": "medium",
        }
    except Exception as e:
        return {"error": str(e), "description": "", "confidence": "low"}
    finally:
        try:
            os.remove(staged)
        except OSError:
            pass


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
        return {"error": f"Tool '{tool_name}' non disponibile. Usa il formato: {{\"done\": true, \"report\": {{...}}}}",
                "disponibili": ["check_display_on", "capture_frames", "detect_motion",
                                "count_objects", "view_frame", "run_analysis",
                                "recalibrate", "read_text"]}


# ── JSON parser ────────────────────────────────────────────────────────────────

_REPORT_KEYS = {"display_on", "success_hint", "motion_detected", "objects_total"}

def _parse_m40_response(raw: str) -> dict | None:
    """Estrae l'oggetto JSON dalla risposta M40. Ritorna None se non trovato."""
    # Cerca JSON in blocchi markdown ``` ... ``` (con o senza 'json')
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1).strip())
            if isinstance(obj, dict):
                # Se M40 ha scritto il report direttamente (senza "done": true) — wrappa
                if _REPORT_KEYS & obj.keys() and "tool" not in obj:
                    return {"done": True, "report": obj}
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    # Usa raw_decode per trovare JSON con "tool", "done" o chiavi report
    decoder = json.JSONDecoder()
    positions = [i for i, c in enumerate(raw) if c == "{"]
    best = None
    for pos in positions:
        try:
            obj, _ = decoder.raw_decode(raw, pos)
            if not isinstance(obj, dict):
                continue
            is_tool = "tool" in obj or "done" in obj
            is_report = bool(_REPORT_KEYS & obj.keys()) and "tool" not in obj
            if is_tool or is_report:
                candidate = obj
                if is_report and "done" not in candidate:
                    candidate = {"done": True, "report": obj}
                if best is None or len(candidate) > len(best):
                    best = candidate
        except (json.JSONDecodeError, ValueError):
            pass
    return best


def _m40_step(messages: list[dict], max_tokens: int = 600) -> str:
    """Chiama M40 per un singolo passo del mini-loop."""
    from agent.m40_client import M40Client
    client = M40Client(timeout=300)  # 5 min — il system prompt è lungo
    result = client.generate(messages, max_tokens=max_tokens, label="M40→Observer")
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
    _last_detect_motion: dict | None = None  # risultato grezzo per post-processing

    # view_frame parallelo: lanciato subito dopo capture_frames,
    # risultato disponibile quando M40 lo chiede
    _vf_future: dict | None = None   # None = non ancora lanciato
    _vf_lock = threading.Event()     # segnala completamento

    def _launch_view_frame_async(path: str) -> None:
        nonlocal _vf_future
        log(f"  [view_frame async] avvio MI50 vision su {path.split('/')[-1]}")
        try:
            result = _tool_view_frame(path)
        except Exception as e:
            result = {"error": str(e), "description": "", "confidence": "low"}
        _vf_future = result
        _vf_lock.set()
        log(f"  [view_frame async] completato: {str(result.get('description',''))[:80]}")

    messages = [
        {"role": "system", "content": _OBSERVER_SYSTEM},
        {"role": "user",   "content": f"GOAL: {goal}\n\nInizia l'osservazione seguendo la sequenza standard: check_display_on → capture_frames → view_frame → detect_motion/count_objects → report."},
    ]

    steps_taken = 0
    final_report = None
    # Dati accumulati durante l'osservazione (per fallback report)
    _accumulated = {
        "display_on": None,
        "objects_total": 0,
        "motion_detected": False,
        "motion_confidence": "low",
        "centroid_displacement": 0.0,
        "text": "",
        "view_description": "",
    }

    for step in range(max_steps):
        steps_taken = step + 1
        log(f"  [Observer step {steps_taken}/{max_steps}]")

        try:
            # Ultimi 2 passi: report finale può essere verboso → più token
            step_max_tokens = 1500 if (max_steps - step) <= 2 else 600
            raw = _m40_step(messages, max_tokens=step_max_tokens)
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

        # view_frame: usa il risultato precalcolato in parallelo se disponibile
        if tool_name == "view_frame":
            if _vf_future is not None:
                log("  [view_frame] risultato già pronto (parallelo) ✓")
                tool_result = _vf_future
            elif _vf_lock.is_set():
                tool_result = _vf_future
            else:
                # Async non ancora completato — aspetta (max 120s)
                log("  [view_frame] attendo completamento MI50 vision...")
                _vf_lock.wait(timeout=120)
                tool_result = _vf_future or {"error": "timeout", "description": "", "confidence": "low"}
        else:
            tool_result = _call_vision_tool(tool_name, tool_args, frame_paths)

        log(f"  ← {json.dumps(tool_result, ensure_ascii=False, default=str)[:150]}")

        if tool_name == "check_display_on":
            last_white_ratio = float(tool_result.get("white_ratio", 0.0))
            _accumulated["display_on"] = tool_result.get("on")

        # Salva risultato detect_motion per post-processing
        if tool_name == "detect_motion":
            _last_detect_motion = tool_result
            if tool_result.get("motion_detected"):
                _accumulated["motion_detected"] = True
                _accumulated["motion_confidence"] = tool_result.get("confidence", "low")
                _accumulated["centroid_displacement"] = float(tool_result.get("centroid_displacement", 0.0))

        if tool_name == "count_objects":
            _accumulated["objects_total"] = tool_result.get("total", 0)

        if tool_name == "read_text" and tool_result.get("text_found"):
            _accumulated["text"] = tool_result.get("text", "")

        if tool_name == "view_frame" and tool_result.get("description"):
            _accumulated["view_description"] = tool_result["description"][:200]

        # Dopo capture_frames: lancia view_frame in parallelo mentre M40 pensa
        if tool_name == "capture_frames" and frame_paths:
            _vf_lock.clear()
            _vf_future = None
            t = threading.Thread(
                target=_launch_view_frame_async,
                args=(frame_paths[0],),
                daemon=True,
            )
            t.start()

        # Hint contestuale per count_objects con display denso
        extra = ""
        if tool_name == "count_objects" and last_white_ratio >= 0.02:
            extra = (f"\nNOTA: white_ratio={last_white_ratio:.3f} — "
                     f"i blocks sono probabilmente contenuto visivo (grafica densa), "
                     f"non riflessi ambientali.")
        # CRITICO: detect_motion è più affidabile di view_frame per il movimento
        if tool_name == "detect_motion" and tool_result.get("motion_detected"):
            conf = tool_result.get("confidence", "low")
            extra += (f"\nIMPORTANTE: detect_motion usa diff pixel tra frame multipli — "
                      f"fonte primaria per il movimento (confidence={conf}). "
                      f"view_frame vede UN SOLO frame e può dire 'statiche' anche con animazione. "
                      f"Se motion_detected=True → il display mostra ANIMAZIONE in corso.")

        passi_rimasti = max_steps - steps_taken
        compact_hint = ""
        if passi_rimasti <= 2:
            compact_hint = (
                "\n\n⚠️ REPORT COMPATTO: rispondi con {\"done\": true, \"report\": {...}} "
                "SENZA includere arrays di dots/segments (solo i conteggi: objects_total, motion_detected, text). "
                "Mantieni: display_on, motion_detected, motion_confidence, text, description (breve), success_hint, reason."
            )
        result_msg = (
            f"Risultato {tool_name}:\n"
            f"{json.dumps(tool_result, ensure_ascii=False, default=str, indent=2)}"
            f"{extra}\n\n"
            f"Cosa fai adesso? Ricorda: max {passi_rimasti} passi rimasti "
            f"(incluso il report finale). Se hai dubbi sui numeri usa view_frame o run_analysis."
            f"{compact_hint}"
        )
        messages.append({"role": "user", "content": result_msg})

    if final_report is None:
        log("  Observer: nessun report — fallback con dati accumulati")
        # Costruisce report dai dati raccolti durante i tool calls
        has_data = (_accumulated["display_on"] is not None or
                    _accumulated["objects_total"] > 0 or
                    _accumulated["motion_detected"] or
                    bool(_accumulated["text"]))
        final_report = {
            "display_on":            _accumulated["display_on"],
            "objects_total":         _accumulated["objects_total"],
            "dots":                  [],
            "segments":              [],
            "motion_detected":       _accumulated["motion_detected"],
            "motion_confidence":     _accumulated["motion_confidence"],
            "centroid_displacement": _accumulated["centroid_displacement"],
            "text":                  _accumulated["text"],
            "description":           _accumulated["view_description"] or "Osservazione incompleta (M40 non ha prodotto report)",
            "success_hint":          has_data and bool(_accumulated["text"] or _accumulated["motion_detected"]),
            "reason":                "Fallback: dati raccolti dai tool calls, M40 non ha completato il report finale",
        }
        if has_data:
            log(f"  Observer fallback: display_on={final_report['display_on']}, "
                f"motion={final_report['motion_detected']}, text='{final_report['text']}', "
                f"objects={final_report['objects_total']}")

    # ── Post-processing: detect_motion override ──────────────────────────────
    # view_frame vede un singolo frame → può dire "statiche" anche con animazione.
    # detect_motion usa diff tra frame multipli → più affidabile.
    # Se detect_motion=True (medium/high) ma il report dice motion=False o
    # success_hint=False con goal che implica animazione → correggiamo.
    if _last_detect_motion and _last_detect_motion.get("motion_detected"):
        dm_conf = _last_detect_motion.get("confidence", "low")
        if dm_conf in ("high", "medium"):
            # Forza i campi motion nel report
            if not final_report.get("motion_detected"):
                log(f"  [Observer] motion override: detect_motion={dm_conf} "
                    f"→ motion_detected=True nel report")
                final_report["motion_detected"] = True
                final_report["motion_confidence"] = dm_conf
                final_report["centroid_displacement"] = float(
                    _last_detect_motion.get("centroid_displacement", 0.0)
                )

            # Se goal implica animazione e success_hint=False → correggi
            _anim_kw = ("pallina", "boid", "moto", "muov", "animaz", "ball",
                        "snake", "conway", "fish", "predator", "prey", "punto",
                        "firework", "sprite", "bounce", "rimbalz",
                        "orologio", "lancett", "clock", "analog")
            if not final_report.get("success_hint") and any(kw in goal.lower() for kw in _anim_kw):
                log(f"  [Observer] success_hint override: motion=True + goal animazione "
                    f"→ success_hint=True")
                final_report["success_hint"] = True
                final_report["reason"] = (
                    (final_report.get("reason", "") or "") +
                    f" [auto: detect_motion={dm_conf}, animazione confermata]"
                ).strip()

    # ── Post-processing: OCR text override ──────────────────────────────────
    # Se OCR ha trovato testo nel formato HH:MM:SS e success_hint=False → correggi
    ocr_text = final_report.get("text", "")
    import re as _re
    if (ocr_text and not final_report.get("success_hint") and
            _re.search(r"\d{1,2}:\d{2}(:\d{2})?", ocr_text)):
        log(f"  [Observer] success_hint override: OCR trovato '{ocr_text}' → success_hint=True")
        final_report["success_hint"] = True
        final_report["reason"] = (
            (final_report.get("reason", "") or "") +
            f" [auto: OCR text='{ocr_text}']"
        ).strip()

    final_report["steps_taken"] = steps_taken
    return final_report
