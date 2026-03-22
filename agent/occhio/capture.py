"""
capture.py — cattura frame con timing interno.

capture_frames(n, interval_ms) → list[str]
    Cattura N frame a distanza fissa nel tempo.
    Il timing è gestito interamente qui (non da MI50 o M40).
    Usa automaticamente il preset da eye_calibration.json.
    Retry adattivo se il primo frame è sovraesposto o sottoesposto.

check_display_on() → dict
    Check rapido: il display mostra qualcosa?
"""

import os
import sys
import time
import tempfile
from pathlib import Path

from agent.occhio._common import (
    PRESETS, DEFAULT_PRESET, CAPTURE_WIDTH, CAPTURE_HEIGHT, CAPTURE_QUALITY,
    THRESHOLD_OLED, load_calibration, log
)

# Importa l'infrastruttura SSH/SCP già esistente da grab.py
from agent.grab import grab_now as _grab_now_raw


# ── Analisi qualità frame (veloce, solo white_ratio) ─────────────────────────

def _white_ratio(img_path: str) -> float:
    """Ritorna la frazione di pixel sopra soglia. Ritorna -1 se errore."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return 0.05  # Assume OK se PIL non disponibile

    try:
        img = Image.open(img_path).convert("L")
        arr = np.array(img)
        return float((arr > THRESHOLD_OLED).sum()) / arr.size
    except Exception:
        return -1.0


def _grab_with_preset(n: int, interval_ms: int, preset: str) -> list[str]:
    """
    Cattura N frame con il preset indicato.
    Usa grab_now() (SSH al Pi) con timing interno.
    Ritorna lista di path locali.
    """
    p = PRESETS.get(preset, PRESETS[DEFAULT_PRESET])

    # grab_now gestisce SSH, SCP e timing lato Raspberry
    result = _grab_now_raw(
        n_frames=n,
        interval_ms=interval_ms,
        width=CAPTURE_WIDTH,
        height=CAPTURE_HEIGHT,
        quality=CAPTURE_QUALITY,
    )

    if not result.get("ok"):
        log(f"grab_now fallito con preset={preset}: {result.get('error','?')}")
        return []

    return result.get("frame_paths", [])


# ── Preset alternativo per retry adattivo ────────────────────────────────────

_FALLBACK_FOR = {
    "standard":     "bright",
    "bright":       "dark",
    "dark":         "oled_only",
    "oled_only":    "high_contrast",
    "high_contrast":"standard",
}


# ── API pubblica ──────────────────────────────────────────────────────────────

def capture_frames(n: int = 3, interval_ms: int = 1000) -> list[str]:
    """
    Cattura N frame a distanza interval_ms ms l'uno dall'altro.

    - Usa automaticamente il preset salvato da calibrate_eye().
    - Se il primo frame è sovraesposto (white_ratio > 0.60) o sottoesposto
      (white_ratio < 0.001), ritenta con preset alternativo (1 solo retry).
    - Il timing è gestito interamente da questa funzione.

    Ritorna lista di path JPEG locali (può essere vuota se Pi non raggiungibile).
    """
    cal   = load_calibration()
    preset = cal.get("preset", DEFAULT_PRESET)

    log(f"capture_frames(n={n}, interval={interval_ms}ms, preset={preset})")
    frames = _grab_with_preset(n, interval_ms, preset)

    if not frames:
        return []

    # Verifica qualità del primo frame
    wr = _white_ratio(frames[0])
    log(f"  primo frame white_ratio={wr:.3f}")

    if wr > 0.60:
        log(f"  sovraesposto (wr={wr:.2f}) — retry con preset alternativo")
        alt = _FALLBACK_FOR.get(preset, DEFAULT_PRESET)
        frames_retry = _grab_with_preset(n, interval_ms, alt)
        if frames_retry:
            wr2 = _white_ratio(frames_retry[0])
            log(f"  retry {alt}: white_ratio={wr2:.3f}")
            if wr2 < wr:
                return frames_retry
        # Fallback: usa frames originali
        return frames

    if wr < 0.001 and wr >= 0:
        log(f"  sottoesposto/buio (wr={wr:.4f}) — retry con preset alternativo")
        alt = _FALLBACK_FOR.get(preset, DEFAULT_PRESET)
        frames_retry = _grab_with_preset(n, interval_ms, alt)
        if frames_retry:
            wr2 = _white_ratio(frames_retry[0])
            log(f"  retry {alt}: white_ratio={wr2:.4f}")
            if wr2 > wr:
                return frames_retry
        return frames

    return frames


def check_display_on() -> dict:
    """
    Verifica rapida se il display mostra qualcosa.
    Cattura 1 frame e controlla white_ratio.

    Ritorna:
        {
            "on": bool,
            "white_ratio": float,
            "preset_used": str,
        }
    """
    cal    = load_calibration()
    preset = cal.get("preset", DEFAULT_PRESET)

    frames = _grab_with_preset(1, 0, preset)
    if not frames:
        return {"on": False, "white_ratio": 0.0, "preset_used": preset,
                "error": "Pi non raggiungibile o webcam assente"}

    wr = _white_ratio(frames[0])
    on = wr > 0.001  # soglia abbassata: 0.003→0.001 per display sparsi (Conway, snake piccolo)

    log(f"check_display_on: white_ratio={wr:.4f} → {'ON' if on else 'OFF'}")
    return {"on": on, "white_ratio": round(wr, 4), "preset_used": preset}
