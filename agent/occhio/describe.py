"""
describe.py — descrizione libera guidata da un obiettivo.

describe_scene(frame_paths, goal) → dict
    Descrizione generale di cosa vedi, guidata da un goal.
    Pipeline: count_objects → detect_motion → M40 VisualJudge → MI50 fallback

    È il tool più flessibile ma anche il più lento.
    Usare come ultima risorsa, non come prima scelta.
"""

import json
import re
import sys

from agent.occhio._common import log
from agent.occhio.analyze import detect_motion, count_objects


# ── Descrizione testuale strutturata ─────────────────────────────────────────

def _build_text_description(
    frame_paths: list[str],
    objects: dict,
    motion: dict | None,
    goal: str,
) -> str:
    """
    Costruisce una descrizione testuale strutturata per M40 VisualJudge.
    """
    lines = [f"OBIETTIVO: {goal}", ""]

    # Oggetti
    total = objects.get("total", 0)
    dots  = objects.get("dots", [])
    segs  = objects.get("segments", [])
    blocks = objects.get("blocks", 0)

    lines.append(f"OGGETTI SUL DISPLAY: {total} totali (esclusi {blocks} blocchi grandi)")
    if dots:
        coords = ", ".join(f"({d['cx']},{d['cy']})" for d in dots[:5])
        lines.append(f"  Punti piccoli (dot): {len(dots)} — {coords}")
    if segs:
        coords = ", ".join(f"({s['cx']},{s['cy']})" for s in segs[:5])
        lines.append(f"  Segmenti medi: {len(segs)} — {coords}")
    if blocks:
        lines.append(f"  Blocchi grandi (artefatti): {blocks} — probabilmente riflessi ambientali")

    lines.append(f"  Descrizione: {objects.get('description', '—')}")
    lines.append("")

    # Movimento
    if motion is not None:
        m_detected = motion.get("motion_detected", False)
        mean_diff  = motion.get("mean_diff", 0.0)
        displace   = motion.get("centroid_displacement", 0.0)
        conf       = motion.get("confidence", "low")
        lines.append(f"MOVIMENTO: {'RILEVATO' if m_detected else 'NON RILEVATO'} "
                     f"(confidence={conf}, diff={mean_diff:.1f}, displacement={displace:.1f}px)")
    else:
        lines.append("MOVIMENTO: non analizzato (frame singolo)")

    lines.append("")
    lines.append(f"Frame analizzati: {len(frame_paths)}")

    return "\n".join(lines)


# ── M40 VisualJudge ───────────────────────────────────────────────────────────

_M40_JUDGE_SYSTEM = """\
Sei un giudice tecnico per display OLED Arduino.
Ricevi una descrizione testuale di cosa è visibile sul display e un obiettivo.
Valuta se il display mostra il comportamento atteso.

Rispondi SOLO con JSON:
{"success": true/false, "reason": "spiegazione concisa (max 120 car)", "confidence": 0.0-1.0}

Nessun testo prima o dopo il JSON.
"""


def _m40_judge(description: str) -> dict:
    """Chiama M40 VisualJudge con la descrizione testuale."""
    try:
        from agent.m40_client import M40Client
    except ImportError:
        return {"success": False, "reason": "M40 non disponibile", "confidence": 0.0}

    client = M40Client()
    messages = [
        {"role": "system", "content": _M40_JUDGE_SYSTEM},
        {"role": "user",   "content": description},
    ]

    try:
        result = client.generate(messages, max_tokens=100, label="M40→VisualJudge")
        raw = result.get("response", result.get("raw", ""))
    except Exception as e:
        return {"success": False, "reason": f"M40 errore: {e}", "confidence": 0.0}

    # Parse JSON
    text = raw.strip() if isinstance(raw, str) else ""
    for m in reversed(list(re.finditer(r"\{.*?\}", text, re.DOTALL))):
        try:
            parsed = json.loads(m.group(0))
            if "success" in parsed:
                return parsed
        except (json.JSONDecodeError, AttributeError):
            pass

    return {"success": False, "reason": text[:120], "confidence": 0.3}


# ── MI50 vision fallback ──────────────────────────────────────────────────────

def _mi50_vision_fallback(frame_paths: list[str], goal: str) -> dict:
    """
    Fallback: invia le immagini direttamente a MI50-vision.
    Usato solo se M40 ha confidence < 0.6.
    Context isolato — non inquina il context principale.
    """
    try:
        from agent.mi50_client import MI50Client
    except ImportError:
        return {"success": False, "reason": "MI50 non disponibile", "confidence": 0.0}

    client = MI50Client()

    system = (
        "Sei un giudice tecnico per display OLED Arduino.\n"
        f"OBIETTIVO: {goal}\n\n"
        "Guarda le immagini e valuta se il display mostra il comportamento atteso.\n"
        "Rispondi SOLO con JSON:\n"
        '{"success": true/false, "reason": "spiegazione concisa", "confidence": 0.0-1.0}'
    )

    messages = [{"role": "user", "content": "Valuta il display OLED nelle immagini."}]

    # Usa solo i primi 2 frame per non saturare il context MI50
    imgs = frame_paths[:2]

    try:
        if len(imgs) == 1:
            raw = client.chat_with_image(
                messages=messages, image_path=imgs[0],
                system=system, max_new_tokens=150, enable_thinking=False,
            )
        else:
            raw = client.chat_with_images(
                messages=messages, image_paths=imgs,
                system=system, max_new_tokens=150, enable_thinking=False,
            )
    except AttributeError:
        # Fallback a singola immagine se chat_with_images non disponibile
        try:
            raw = client.chat_with_image(
                messages=messages, image_path=imgs[0],
                system=system, max_new_tokens=150, enable_thinking=False,
            )
        except Exception as e:
            return {"success": False, "reason": f"MI50 vision fallita: {e}", "confidence": 0.0}
    except Exception as e:
        return {"success": False, "reason": f"MI50 vision fallita: {e}", "confidence": 0.0}

    text = raw.strip() if isinstance(raw, str) else ""
    for m in reversed(list(re.finditer(r"\{.*?\}", text, re.DOTALL))):
        try:
            parsed = json.loads(m.group(0))
            if "success" in parsed:
                return parsed
        except (json.JSONDecodeError, AttributeError):
            pass

    return {"success": False, "reason": text[:120], "confidence": 0.3}


# ── API pubblica ──────────────────────────────────────────────────────────────

def describe_scene(frame_paths: list[str], goal: str) -> dict:
    """
    Descrizione generale di cosa è visibile, guidata da un obiettivo.

    Pipeline:
    1. count_objects → blob stats
    2. detect_motion → motion stats (se > 1 frame)
    3. Costruisce descrizione testuale strutturata
    4. M40 VisualJudge (veloce, solo testo, no immagini)
    5. Se M40 confidence < 0.6 → MI50-vision fallback (lento, immagini)

    Input:
        frame_paths: lista path JPEG (da capture_frames)
        goal:        stringa obiettivo (es. "verifica 5 palline che si muovono")

    Output:
        {
            "description":    str,
            "success_hint":   bool,   # True se il goal sembra raggiunto
            "confidence":     float,  # 0.0–1.0
            "reason":         str,
            "pipeline_used":  "m40"|"mi50"|"none",
        }
    """
    if not frame_paths:
        return {
            "description":  "Nessun frame fornito",
            "success_hint": False,
            "confidence":   0.0,
            "reason":       "Nessun frame",
            "pipeline_used": "none",
        }

    log(f"describe_scene: {len(frame_paths)} frame, goal='{goal[:60]}...'")

    # Step 1: analisi blob
    objects = count_objects(frame_paths)

    # Step 2: movimento (solo se > 1 frame)
    motion = detect_motion(frame_paths) if len(frame_paths) > 1 else None

    # Step 3: descrizione testuale
    text_desc = _build_text_description(frame_paths, objects, motion, goal)
    log(f"  descrizione testuale ({len(text_desc)} chars)")

    # Step 4: M40 VisualJudge
    log("  M40 VisualJudge...")
    m40_result = _m40_judge(text_desc)
    confidence = float(m40_result.get("confidence", 0.5))
    log(f"  M40: success={m40_result.get('success')}, confidence={confidence:.2f}")

    pipeline_used = "m40"

    # Step 5: fallback MI50 se confidence bassa
    if confidence < 0.6:
        log("  M40 confidence bassa → MI50-vision fallback")
        mi50_result = _mi50_vision_fallback(frame_paths, goal)
        mi50_conf = float(mi50_result.get("confidence", 0.4))

        if mi50_conf > confidence:
            log(f"  MI50 migliore: confidence={mi50_conf:.2f}")
            final_result = mi50_result
            pipeline_used = "mi50"
        else:
            log(f"  M40 preferito anche con confidence bassa ({confidence:.2f} vs MI50 {mi50_conf:.2f})")
            final_result = m40_result
    else:
        final_result = m40_result

    return {
        "description":   text_desc,
        "success_hint":  bool(final_result.get("success", False)),
        "confidence":    float(final_result.get("confidence", confidence)),
        "reason":        final_result.get("reason", ""),
        "pipeline_used": pipeline_used,
        "objects":       objects,
        "motion":        motion,
    }
