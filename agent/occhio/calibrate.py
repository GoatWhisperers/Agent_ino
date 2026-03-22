"""
calibrate.py — calibrazione camera per il setup fisico corrente.

calibrate_eye(target) → dict
    Testa tutti i preset camera, trova il migliore per il target,
    salva il risultato in workspace/eye_calibration.json.

    target: "oled" | "led" | "general"
"""

import os
import sys
import time
from datetime import datetime

from agent.occhio._common import (
    PRESETS, DEFAULT_PRESET, CAPTURE_WIDTH, CAPTURE_HEIGHT, CAPTURE_QUALITY,
    THRESHOLD_OLED, load_calibration, save_calibration, log
)
from agent.grab import grab_now as _grab_now_raw


# ── Cattura singolo frame con preset specifico ────────────────────────────────

def _capture_one(preset: str) -> str | None:
    """Cattura un frame con un preset specifico. Ritorna path locale o None."""
    result = _grab_now_raw(
        n_frames=1,
        interval_ms=0,
        width=CAPTURE_WIDTH,
        height=CAPTURE_HEIGHT,
        quality=CAPTURE_QUALITY,
    )
    if not result.get("ok") or not result.get("frame_paths"):
        log(f"  cattura fallita per preset={preset}")
        return None
    return result["frame_paths"][0]


# ── Analisi qualità per target ────────────────────────────────────────────────

def _analyze_for_target(img_path: str, target: str) -> dict:
    """
    Calcola score di qualità di un frame per il target dato.

    Ritorna dict con: white_ratio, blob_count, mean_brightness, score, notes
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return {"score": 0.0, "error": "PIL/numpy non disponibili"}

    try:
        img = Image.open(img_path).convert("L")
        arr = np.array(img)
        h, w = arr.shape

        binary = (arr > THRESHOLD_OLED).astype(np.uint8)
        white_pixels  = int(binary.sum())
        total_pixels  = h * w
        white_ratio   = white_pixels / total_pixels
        mean_br       = float(arr.mean())
        max_br        = int(arr.max())
        saturated     = white_ratio > 0.40

        # Blob count semplice (scan per righe, step=4)
        blob_count = 0
        for y in range(0, h, 4):
            row = binary[y]
            in_blob = False
            for x in range(w):
                if row[x] and not in_blob:
                    in_blob = True
                    blob_count += 1
                elif not row[x]:
                    in_blob = False

        # Score per target
        score = 0.0
        notes = []

        if target == "oled":
            # Vogliamo: white_ratio 0.05–0.40, blob_count > 2, non saturato
            if white_ratio < 0.001:
                score = 0.0
                notes.append("display spento o non visibile")
            elif saturated:
                score = 0.05
                notes.append("sovraesposto")
            else:
                # Picco quando white_ratio ≈ 0.10-0.25
                wr_score = 1.0 - abs(white_ratio - 0.15) / 0.30
                wr_score = max(0.0, min(1.0, wr_score))
                blob_bonus = min(1.0, blob_count / 10)
                noise_penalty = mean_br / 255
                score = 0.5 * wr_score + 0.3 * blob_bonus - 0.2 * noise_penalty
                score = max(0.0, score)
                notes.append(f"wr={white_ratio:.2%}, blobs={blob_count}")

        elif target == "led":
            # Vogliamo: range brightness ampio (LED puntiforme su sfondo scuro)
            brightness_range = max_br - mean_br
            score = min(1.0, brightness_range / 200.0) * (1 - mean_br / 255)
            notes.append(f"range={brightness_range:.0f}, mean={mean_br:.0f}")

        else:  # "general"
            # Bilanciamento contrasto/rumore
            if mean_br < 5:
                score = 0.3  # Troppo buio
                notes.append("troppo buio")
            elif saturated:
                score = 0.2
                notes.append("sovraesposto")
            else:
                contrast_score = min(1.0, max_br / 255)
                noise_score = 1.0 - mean_br / 128  # meno rumore = meglio
                score = 0.6 * contrast_score + 0.4 * max(0, noise_score)
                notes.append(f"contrast={max_br}, noise={mean_br:.0f}")

        return {
            "white_ratio":     round(white_ratio, 4),
            "blob_count":      blob_count,
            "mean_brightness": round(mean_br, 1),
            "max_brightness":  max_br,
            "saturated":       saturated,
            "score":           round(max(0.0, min(1.0, score)), 4),
            "notes":           "; ".join(notes),
        }

    except Exception as e:
        log(f"  errore analisi {img_path}: {e}")
        return {"score": 0.0, "error": str(e)}


# ── API pubblica ──────────────────────────────────────────────────────────────

def calibrate_eye(target: str = "oled") -> dict:
    """
    Trova i parametri camera ottimali per il setup fisico corrente.

    target: "oled" | "led" | "general"

    Procedura:
    1. Cattura 1 frame per ogni preset
    2. Calcola quality score per target
    3. Salva preset vincente in workspace/eye_calibration.json
    4. Ritorna report completo

    Output:
        {
            "best_preset":   str,
            "target":        str,
            "scores":        {preset: float, ...},
            "white_ratio_at_calibration": float,
            "calibrated_at": str (ISO),
            "results":       {preset: {score, white_ratio, blob_count, notes}, ...},
        }
    """
    if target not in ("oled", "led", "general"):
        target = "oled"
        log(f"target non riconosciuto, uso 'oled'")

    log(f"calibrate_eye(target={target}) — testo {len(PRESETS)} preset...")

    results = {}

    for preset_name in PRESETS:
        log(f"  preset '{preset_name}': {PRESETS[preset_name]['desc']}")
        img_path = _capture_one(preset_name)

        if img_path is None:
            results[preset_name] = {"ok": False, "score": 0.0, "error": "cattura fallita"}
            continue

        analysis = _analyze_for_target(img_path, target)
        analysis["ok"] = True
        analysis["img"] = img_path
        results[preset_name] = analysis

        log(f"    score={analysis['score']:.4f}  {analysis.get('notes','')}")

        # Pausa tra catture per permettere alla camera di settarsi
        time.sleep(0.5)

    # Trova best
    best = max(
        (k for k in results if results[k].get("ok")),
        key=lambda k: results[k]["score"],
        default=DEFAULT_PRESET,
    )

    scores = {k: results[k].get("score", 0.0) for k in results}
    wr_best = results.get(best, {}).get("white_ratio", 0.0)

    cal_data = {
        "preset":                    best,
        "target":                    target,
        "calibrated_at":             datetime.utcnow().isoformat(),
        "scores":                    scores,
        "white_ratio_at_calibration": wr_best,
    }

    save_calibration(cal_data)
    log(f"calibrate_eye: preset scelto = '{best}' (score={scores.get(best, 0):.4f})")
    log(f"  salvato in workspace/eye_calibration.json")

    return {
        **cal_data,
        "results": results,
    }
