"""
analyze.py — analisi pixel su frame già catturati.

detect_motion(frame_paths)  → dict  — c'è movimento tra i frame?
count_objects(frame_paths)  → dict  — quanti oggetti e dove? (blob 2D con coordinate)

Nota: check_display_on() è in capture.py per evitare import circolare.
"""

import sys
from agent.occhio._common import THRESHOLD_OLED, log


# ── Blob 2D con scipy (fallback BFS se scipy non disponibile) ─────────────────

def _label_blobs(binary_arr):
    """
    Etichetta regioni connesse in un array binario 2D.
    Ritorna (labeled_array, num_labels).

    Prova scipy.ndimage.label prima, poi BFS come fallback.
    """
    try:
        from scipy.ndimage import label as sp_label
        import numpy as np
        labeled, n = sp_label(binary_arr)
        return labeled, int(n)
    except ImportError:
        pass

    # Fallback BFS semplice
    import numpy as np
    h, w = binary_arr.shape
    labeled = np.zeros_like(binary_arr, dtype=np.int32)
    current_label = 0

    for sy in range(h):
        for sx in range(w):
            if binary_arr[sy, sx] and not labeled[sy, sx]:
                current_label += 1
                queue = [(sy, sx)]
                labeled[sy, sx] = current_label
                while queue:
                    cy, cx = queue.pop()
                    for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
                        ny, nx = cy+dy, cx+dx
                        if 0 <= ny < h and 0 <= nx < w:
                            if binary_arr[ny, nx] and not labeled[ny, nx]:
                                labeled[ny, nx] = current_label
                                queue.append((ny, nx))

    return labeled, current_label


def _extract_blobs(img_path: str) -> list[dict]:
    """
    Apre un frame, lo converte in grayscale, applica soglia e
    ritorna lista di blob con: cx, cy, area, bbox.

    Categorizzazione area (pixel):
      dot     : ≤ 16px     (pixel singoli, 2×2, 4×4 — tipico OLED)
      segment : 17–200px   (segmenti corpo snake, palline piccole)
      block   : > 200px    (riflessi ambientali, grandi forme geometriche)
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        log("PIL/numpy non disponibili — analisi blob impossibile")
        return []

    try:
        img = Image.open(img_path).convert("L")
        # Crop centro 380×288 per escludere bordi webcam
        w, h = img.size
        mx, my = max(0, (w - 380) // 2), max(0, (h - 288) // 2)
        if w > 380 and h > 288:
            img = img.crop((mx, my, mx + 380, my + 288))

        arr = np.array(img)
        binary = (arr > THRESHOLD_OLED).astype(np.uint8)

        labeled, n_labels = _label_blobs(binary)
        if n_labels == 0:
            return []

        blobs = []
        for label_id in range(1, n_labels + 1):
            ys, xs = np.where(labeled == label_id)
            if len(ys) == 0:
                continue
            area = len(ys)
            cx   = int(xs.mean())
            cy   = int(ys.mean())
            x_min, x_max = int(xs.min()), int(xs.max())
            y_min, y_max = int(ys.min()), int(ys.max())

            if area <= 16:
                kind = "dot"
            elif area <= 200:
                kind = "segment"
            else:
                kind = "block"

            blobs.append({
                "cx": cx, "cy": cy, "area": area, "kind": kind,
                "bbox": [x_min, y_min, x_max, y_max],
            })

        return blobs

    except Exception as e:
        log(f"errore extract_blobs su {img_path}: {e}")
        return []


def _centroids(blobs: list[dict]) -> list[tuple[float, float]]:
    return [(b["cx"], b["cy"]) for b in blobs if b["kind"] != "block"]


# ── detect_motion ─────────────────────────────────────────────────────────────

def detect_motion(frame_paths: list[str]) -> dict:
    """
    Rileva se c'è movimento tra i frame.

    Input:  lista di path JPEG (da capture_frames)
    Output:
        {
            "motion_detected": bool,
            "mean_diff":       float,   # diff pixel medio inter-frame
            "centroid_displacement": float,  # spostamento medio centroidi
            "confidence":      "high"|"medium"|"low",
            "frames_analyzed": int,
        }

    mean_diff > 2.0 → motion detected
    centroid_displacement: distingue rumore (flickering) da movimento reale.
    """
    if len(frame_paths) < 2:
        return {
            "motion_detected": False,
            "mean_diff": 0.0,
            "centroid_displacement": 0.0,
            "confidence": "low",
            "frames_analyzed": len(frame_paths),
            "note": "servono almeno 2 frame",
        }

    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return {
            "motion_detected": False,
            "mean_diff": 0.0,
            "centroid_displacement": 0.0,
            "confidence": "low",
            "error": "PIL/numpy non disponibili",
            "frames_analyzed": 0,
        }

    arrays = []
    for p in frame_paths:
        try:
            img = Image.open(p).convert("L")
            arrays.append(np.array(img, dtype=np.float32))
        except Exception as e:
            log(f"  skip frame {p}: {e}")

    if len(arrays) < 2:
        return {
            "motion_detected": False, "mean_diff": 0.0,
            "centroid_displacement": 0.0, "confidence": "low",
            "frames_analyzed": len(arrays),
        }

    # Mean diff inter-frame (tra frame consecutivi)
    diffs = []
    for i in range(len(arrays) - 1):
        d = float(np.abs(arrays[i] - arrays[i+1]).mean())
        diffs.append(d)
    mean_diff = float(sum(diffs) / len(diffs))

    # Centroid displacement (frame 0 vs frame -1)
    blobs_first = _extract_blobs(frame_paths[0])
    blobs_last  = _extract_blobs(frame_paths[-1])

    c_first = _centroids(blobs_first)
    c_last  = _centroids(blobs_last)

    displacement = 0.0
    if c_first and c_last:
        # Distanza media tra centroidi più vicini
        import math
        matched = 0
        total_dist = 0.0
        for cx1, cy1 in c_first:
            if not c_last:
                break
            best = min(c_last, key=lambda p: (p[0]-cx1)**2 + (p[1]-cy1)**2)
            dist = math.sqrt((best[0]-cx1)**2 + (best[1]-cy1)**2)
            total_dist += dist
            matched += 1
        if matched:
            displacement = total_dist / matched

    motion = mean_diff > 2.0

    # Confidence: alta se sia diff che displacement concordano
    if motion and displacement > 3.0:
        confidence = "high"
    elif motion or displacement > 5.0:
        confidence = "medium"
    else:
        confidence = "low"

    log(f"detect_motion: mean_diff={mean_diff:.2f}, displacement={displacement:.1f}, "
        f"motion={motion}, confidence={confidence}")

    return {
        "motion_detected": motion,
        "mean_diff":       round(mean_diff, 2),
        "centroid_displacement": round(displacement, 1),
        "confidence":      confidence,
        "frames_analyzed": len(arrays),
    }


# ── count_objects ─────────────────────────────────────────────────────────────

def count_objects(frame_paths: list[str]) -> dict:
    """
    Conta e localizza oggetti sul display.

    Input:  lista di path JPEG (usa primo frame o media se più frame)
    Output:
        {
            "total":    int,   # dot + segment (block esclusi — quasi sempre artefatti)
            "dots":     list[{cx, cy, area}],
            "segments": list[{cx, cy, area}],
            "blocks":   int,   # segnalati ma non contati
            "description": str,
        }
    """
    if not frame_paths:
        return {"total": 0, "dots": [], "segments": [], "blocks": 0,
                "description": "Nessun frame fornito"}

    # Usa il frame più centrale della sequenza per ridurre rumore di movimento
    idx = len(frame_paths) // 2
    path = frame_paths[idx]

    blobs = _extract_blobs(path)
    if not blobs:
        return {"total": 0, "dots": [], "segments": [], "blocks": 0,
                "description": "Display probabilmente spento o nessun oggetto rilevato"}

    dots     = [{"cx": b["cx"], "cy": b["cy"], "area": b["area"]}
                for b in blobs if b["kind"] == "dot"]
    segments = [{"cx": b["cx"], "cy": b["cy"], "area": b["area"]}
                for b in blobs if b["kind"] == "segment"]
    blocks   = sum(1 for b in blobs if b["kind"] == "block")

    total = len(dots) + len(segments)

    # Descrizione testuale strutturata
    parts = []
    if dots:
        positions = _position_words(dots)
        parts.append(f"{len(dots)} punto/i piccoli ({', '.join(positions)})")
    if segments:
        positions = _position_words(segments)
        parts.append(f"{len(segments)} segmento/i medi ({', '.join(positions)})")
    if blocks:
        parts.append(f"{blocks} blocco/i grande/i (artefatti ambientali, non contati)")

    description = "; ".join(parts) if parts else "Nessun oggetto rilevato"

    log(f"count_objects: total={total}, dots={len(dots)}, segments={len(segments)}, blocks={blocks}")

    return {
        "total":       total,
        "dots":        dots,
        "segments":    segments,
        "blocks":      blocks,
        "description": description,
    }


def _position_words(blobs: list[dict]) -> list[str]:
    """Converte coordinate in parole posizionali (alto/centro/basso, sinistra/centro/destra)."""
    # Assume display crop ~380×288
    W, H = 380, 288
    words = []
    for b in blobs[:3]:  # Max 3 descrizioni per evitare output troppo lungo
        cx, cy = b["cx"], b["cy"]
        vert  = "alto" if cy < H//3 else ("basso" if cy > 2*H//3 else "centro")
        horiz = "sinistra" if cx < W//3 else ("destra" if cx > 2*W//3 else "centro")
        words.append(f"{vert}-{horiz}")
    if len(blobs) > 3:
        words.append(f"...+{len(blobs)-3}")
    return words
