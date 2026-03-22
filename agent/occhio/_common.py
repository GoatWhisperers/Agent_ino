"""
_common.py — costanti e utility condivise tra i tool visivi.
"""

import json
import os
import sys
from pathlib import Path

# Path root progetto (due livelli sopra questo file)
_PROJECT_ROOT = Path(__file__).parent.parent.parent

CALIBRATION_FILE = _PROJECT_ROOT / "workspace" / "eye_calibration.json"
DEFAULT_PRESET   = "standard"

# Preset camera — ogni preset è una combinazione di parametri rpicam-still
PRESETS = {
    "standard": {
        "ev": -0.5, "contrast": 1.8, "awbgains": "2.2,1.8", "sharpness": 2.0,
        "desc": "Default (luci accese, ambiente normale)"
    },
    "dark": {
        "ev": 0.0, "contrast": 2.5, "awbgains": "1.8,1.8", "sharpness": 2.5,
        "desc": "Buio: solo OLED come fonte di luce"
    },
    "bright": {
        "ev": -1.5, "contrast": 1.5, "awbgains": "2.0,1.6", "sharpness": 1.5,
        "desc": "Luce intensa: EV negativo per non saturare OLED"
    },
    "oled_only": {
        "ev": -0.5, "contrast": 3.0, "awbgains": "1.5,1.5", "sharpness": 3.0,
        "desc": "Max contrasto per isolare pixel OLED"
    },
    "high_contrast": {
        "ev": -1.0, "contrast": 2.2, "awbgains": "2.0,1.8", "sharpness": 2.5,
        "desc": "Bilanciamento contrasto/rumore, buono per LED e testo"
    },
}

THRESHOLD_OLED = 160   # pixel > questa soglia → considerato "acceso"
CAPTURE_WIDTH  = 640
CAPTURE_HEIGHT = 480
CAPTURE_QUALITY = 85


def load_calibration() -> dict:
    """
    Legge workspace/eye_calibration.json.
    Ritorna {"preset": "standard", ...} o default se file non esiste.
    """
    if CALIBRATION_FILE.exists():
        try:
            with open(CALIBRATION_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"preset": DEFAULT_PRESET}


def save_calibration(data: dict) -> None:
    """Salva workspace/eye_calibration.json."""
    CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CALIBRATION_FILE, "w") as f:
        json.dump(data, f, indent=2)


def log(msg: str) -> None:
    print(f"[occhio] {msg}", file=sys.stderr, flush=True)
