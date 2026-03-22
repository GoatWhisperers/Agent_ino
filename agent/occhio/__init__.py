"""
agent/occhio — Vision tools modulari per il programmatore di Arduini.

Tool disponibili (usabili da MI50 nel ReAct loop):

  calibrate_eye(target)             → calibrazione camera, salva preset ottimale
  capture_frames(n, interval_ms)    → cattura N frame a intervalli fissi (timing interno)
  check_display_on()                → display attivo? (check rapido)
  detect_motion(frame_paths)        → movimento rilevato tra i frame?
  count_objects(frame_paths)        → quanti oggetti e dove? (blob 2D con coordinate)
  read_text(frame_paths)            → leggi testo sul display (MI50-vision isolata)
  describe_scene(frame_paths, goal) → descrizione libera guidata (M40 + MI50 fallback)

Tutti i tool leggono il preset da workspace/eye_calibration.json (scritto da calibrate_eye).
"""

from agent.occhio.calibrate import calibrate_eye
from agent.occhio.capture import capture_frames
from agent.occhio.capture import check_display_on
from agent.occhio.analyze import detect_motion, count_objects
from agent.occhio.read import read_text
from agent.occhio.describe import describe_scene

__all__ = [
    "calibrate_eye",
    "capture_frames",
    "check_display_on",
    "detect_motion",
    "count_objects",
    "read_text",
    "describe_scene",
]
