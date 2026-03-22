"""
read.py — leggi testo dal display via MI50-vision.

read_text(frame_paths) → dict
    Cerca testo leggibile sul display OLED.
    Usa MI50-vision con context isolato (non inquina il context principale).

    Quando usarlo: task con OLED che mostra score, messaggi, menu.
    NON usarlo per task puramente grafici (palline, boids) — inutile e lento.
"""

import os
import sys
import re
import json
from agent.occhio._common import log
from agent.occhio.analyze import _extract_blobs


# ── Preprocessing immagine ────────────────────────────────────────────────────

def _preprocess_for_ocr(img_path: str) -> str | None:
    """
    Applica preprocessing PIL per migliorare leggibilità testo.
    Ritorna path del file processato (in /tmp) o None se errore.
    """
    try:
        from PIL import Image, ImageEnhance, ImageOps
        import tempfile
    except ImportError:
        return img_path  # Usa originale se PIL non disponibile

    try:
        img = Image.open(img_path).convert("L")

        # Crop centrale 70%
        w, h = img.size
        mx, my = int(w * 0.10), int(h * 0.10)
        img = img.crop((mx, my, w - mx, h - my))

        # Boost contrasto
        img = ImageEnhance.Contrast(img).enhance(3.0)

        # Threshold B&W (Otsu-like: 128 dopo il boost)
        img = img.point(lambda px: 255 if px > 128 else 0, "L")

        # Ingrandisci per facilitare OCR
        img = img.resize((img.width * 2, img.height * 2), Image.NEAREST)

        fd, out_path = tempfile.mkstemp(suffix="_ocr.jpg", prefix="ob_read_")
        os.close(fd)
        img.save(out_path, quality=95)
        return out_path

    except Exception as e:
        log(f"preprocessing OCR fallito: {e}")
        return img_path


# ── MI50-vision isolata ───────────────────────────────────────────────────────

def _mi50_read_text(img_path: str) -> dict:
    """
    Chiama MI50 in modalità vision con context isolato.
    Prompt dedicato: SOLO testo visibile, nessuna descrizione grafica.
    """
    try:
        from agent.mi50_client import MI50Client
    except ImportError:
        return {"text_found": False, "text": "", "confidence": "low",
                "error": "MI50Client non disponibile"}

    client = MI50Client()

    system = (
        "Sei un lettore OCR. Guarda l'immagine e leggi SOLO il testo visibile. "
        "Non descrivere forme, colori o grafica. "
        "Se c'è testo, scrivilo esattamente come appare. "
        "Rispondi SOLO con JSON: {\"text\": \"...\", \"confidence\": \"high|medium|low\"}\n"
        "Se non c'è testo leggibile: {\"text\": \"\", \"confidence\": \"high\"}"
    )

    # Staging: MI50 gira in Docker, vede solo /mnt/raid0
    import shutil, os, time as _time
    _staging_dir = "/mnt/raid0/observer_frames"
    os.makedirs(_staging_dir, exist_ok=True)
    staged = os.path.join(_staging_dir, f"read_{int(_time.time()*1000)}.jpg")
    try:
        shutil.copy2(img_path, staged)
    except Exception as e:
        return {"text_found": False, "text": "", "confidence": "low",
                "error": f"copy frame fallita: {e}"}

    messages = [
        {"role": "user", "content": (
            system + "\n\nLeggi il testo visibile su questo display."
        )}
    ]

    try:
        result = client.generate_with_images(
            messages=messages,
            image_paths=[staged],
            max_new_tokens=100,
            label="Observer→MI50vision→OCR",
        )
        text = result.get("response", result.get("raw", "")).strip()
    except Exception as e:
        return {"text_found": False, "text": "", "confidence": "low",
                "error": f"MI50 vision fallita: {e}"}
    finally:
        try:
            os.remove(staged)
        except OSError:
            pass
    except Exception as e:
        return {"text_found": False, "text": "", "confidence": "low",
                "error": f"MI50 vision fallita: {e}"}

    # Parse JSON
    try:
        # Cerca JSON nella risposta
        m = re.search(r'\{.*?"text".*?\}', text, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            found_text = parsed.get("text", "").strip()
            confidence = parsed.get("confidence", "medium")
            return {
                "text_found": bool(found_text),
                "text":       found_text,
                "confidence": confidence,
            }
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: se la risposta contiene qualcosa di leggibile
    clean = re.sub(r'\{.*?\}', '', text, flags=re.DOTALL).strip()
    if clean and len(clean) < 200:
        return {"text_found": True, "text": clean, "confidence": "low"}

    return {"text_found": False, "text": "", "confidence": "low",
            "raw": text[:200]}


# ── API pubblica ──────────────────────────────────────────────────────────────

def read_text(frame_paths: list[str]) -> dict:
    """
    Leggi testo leggibile dal display OLED.

    Usa MI50-vision con context isolato — NON inquina il context principale MI50.
    Preprocessing PIL per migliorare contrasto del testo.

    Input:  lista di path JPEG (usa il frame con più contrasto)
    Output:
        {
            "text_found":  bool,
            "text":        str,
            "confidence":  "high"|"medium"|"low",
        }

    ATTENZIONE: lento (MI50-vision). Usare solo se il task prevede testo su display.
    """
    if not frame_paths:
        return {"text_found": False, "text": "", "confidence": "low",
                "error": "Nessun frame fornito"}

    # Scegli frame con più blob (più probabilità di avere testo)
    best_path = frame_paths[0]
    if len(frame_paths) > 1:
        best_count = 0
        for p in frame_paths:
            blobs = _extract_blobs(p)
            # Il testo ha molti segment
            segs = sum(1 for b in blobs if b["kind"] == "segment")
            if segs > best_count:
                best_count = segs
                best_path = p

    log(f"read_text: preprocessing {os.path.basename(best_path)}")
    processed = _preprocess_for_ocr(best_path)

    log(f"read_text: MI50-vision OCR (context isolato)...")
    result = _mi50_read_text(processed)

    if processed != best_path and os.path.exists(processed):
        try:
            os.remove(processed)
        except OSError:
            pass

    log(f"read_text: text_found={result['text_found']}, "
        f"text='{result.get('text','')[:40]}', confidence={result.get('confidence')}")

    return result
