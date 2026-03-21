"""
occhio_bionico.py — Pipeline visiva adattiva per il programmatore di Arduini.

Funzioni principali:
  calibrate()         → cattura frame con vari parametri camera, trova il migliore
  process(img_path)   → applica pipeline PIL adattiva → ritorna versioni processate + stats
  describe(img_path)  → genera descrizione testuale strutturata (per M40 VisualJudge)
  judge(img_path, task) → chiama M40 VisualJudge con frame processato + descrizione

Usabile:
  - Da tool_agent.py come sostituto di evaluate_visual
  - Standalone via CLI: python agent/occhio_bionico.py <frame.jpg> [task]
  - Da shell: python agent/occhio_bionico.py calibrate
"""

import os
import sys
import json
import subprocess
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Costanti ─────────────────────────────────────────────────────────────────

RPI_HOST     = "192.168.1.167"
RPI_USER     = "lele"
RPI_PASSWORD = "pippopippo33$$"

CAPTURE_WIDTH  = 640
CAPTURE_HEIGHT = 480
CAPTURE_QUALITY = 85

# Preset camera per diverse condizioni
# ev: esposizione relativa (-2..+2), contrast: 1.0=normale, awbgains: "R,B"
PRESETS = {
    "standard": {
        "ev": -0.5, "contrast": 1.8, "awbgains": "2.2,1.8", "sharpness": 2.0,
        "desc": "Preset di default (luci accese, ambiente normale)"
    },
    "dark": {
        "ev": 0.0,  "contrast": 2.5, "awbgains": "1.8,1.8", "sharpness": 2.5,
        "desc": "Luci spente: più contrasto, EV neutro (OLED è l'unica fonte di luce)"
    },
    "bright": {
        "ev": -1.5, "contrast": 1.5, "awbgains": "2.0,1.6", "sharpness": 1.5,
        "desc": "Luce intensa: EV molto negativo per non sovraesporre l'OLED"
    },
    "oled_only": {
        "ev": -0.5, "contrast": 3.0, "awbgains": "1.5,1.5", "sharpness": 3.0,
        "desc": "Max contrasto per isolare pixel OLED dal rumore"
    },
}

THRESHOLD_OLED = 160   # pixel > threshold → considerato OLED acceso


# ── SSH helper ───────────────────────────────────────────────────────────────

def _ssh(cmd: str, timeout: int = 20) -> dict:
    full = ["sshpass", "-p", RPI_PASSWORD, "ssh",
            "-o", "StrictHostKeyChecking=no",
            f"{RPI_USER}@{RPI_HOST}", cmd]
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        return {"ok": r.returncode == 0, "out": r.stdout, "err": r.stderr}
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {"ok": False, "out": "", "err": str(e)}


def _scp_from(remote: str, local: str, timeout: int = 15) -> bool:
    cmd = ["sshpass", "-p", RPI_PASSWORD, "scp",
           "-o", "StrictHostKeyChecking=no",
           f"{RPI_USER}@{RPI_HOST}:{remote}", local]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# ── Cattura ──────────────────────────────────────────────────────────────────

def capture(preset: str = "standard", out_path: str = None, shutter_us: int = None) -> str | None:
    """
    Cattura un frame sul Raspberry Pi con il preset indicato.
    Ritorna il path locale del JPEG scaricato, o None se errore.

    preset: "standard" | "dark" | "bright" | "oled_only"
    shutter_us: shutter fisso in microsecondi (es. 8000 = 8ms). None = auto.
    """
    if preset not in PRESETS:
        raise ValueError(f"Preset sconosciuto: {preset}. Scegli tra {list(PRESETS.keys())}")

    p = PRESETS[preset]
    remote = f"/tmp/occhio_{preset}_{int(time.time())}.jpg"

    cmd_parts = [
        "rpicam-still",
        "-o", remote,
        "--nopreview", "--immediate",
        "-t", "300",
        "--width",  str(CAPTURE_WIDTH),
        "--height", str(CAPTURE_HEIGHT),
        "-q", str(CAPTURE_QUALITY),
        "--awbgains", p["awbgains"],
        "--contrast",  str(p["contrast"]),
        "--sharpness", str(p["sharpness"]),
        "--ev", str(p["ev"]),
    ]
    if shutter_us is not None:
        cmd_parts += ["--shutter", str(shutter_us)]

    r = _ssh(" ".join(cmd_parts), timeout=20)
    if not r["ok"]:
        print(f"[OcchioBionico] Cattura fallita ({preset}): {r['err'][:100]}", file=sys.stderr)
        return None

    if out_path is None:
        fd, out_path = tempfile.mkstemp(suffix=f"_{preset}.jpg", prefix="ob_")
        os.close(fd)

    if _scp_from(remote, out_path):
        size_kb = os.path.getsize(out_path) // 1024
        print(f"[OcchioBionico] {preset}: {os.path.basename(out_path)} ({size_kb}KB)", file=sys.stderr)
        return out_path
    return None


# ── Analisi pixel ─────────────────────────────────────────────────────────────

def analyze(img_path: str) -> dict:
    """
    Analisi pixel su un frame. Ritorna dict con statistiche.
    Compatibile con il formato usato in evaluator.py.
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return {"error": "PIL/numpy non disponibili"}

    img = Image.open(img_path).convert("L")
    arr = np.array(img)
    h, w = arr.shape

    binary = (arr > THRESHOLD_OLED).astype(np.uint8)
    white_pixels  = int(binary.sum())
    total_pixels  = h * w
    white_ratio   = white_pixels / total_pixels

    # Dove sono i pixel brillanti (bounding box)
    bright_yx = list(zip(*np.where(binary > 0))) if white_pixels > 0 else []
    if bright_yx:
        ys = [p[0] for p in bright_yx]
        xs = [p[1] for p in bright_yx]
        bbox = {"x_min": min(xs), "x_max": max(xs), "y_min": min(ys), "y_max": max(ys),
                "w": max(xs)-min(xs), "h": max(ys)-min(ys)}
        # densità nella bounding box
        zone = arr[bbox["y_min"]:bbox["y_max"]+1, bbox["x_min"]:bbox["x_max"]+1]
        bbox["density"] = round(float((zone > THRESHOLD_OLED).mean()), 4)
    else:
        bbox = None

    # Blob detection semplice (scan per righe)
    blobs = []
    for y in range(0, h, 3):
        row = binary[y]
        in_blob, bstart = False, 0
        for x in range(w):
            if row[x] and not in_blob:
                in_blob, bstart = True, x
            elif not row[x] and in_blob:
                in_blob = False
                if x - bstart >= 2:
                    blobs.append({"x": bstart, "y": y, "w": x - bstart})
        if in_blob and w - bstart >= 2:
            blobs.append({"x": bstart, "y": y, "w": w - bstart})

    small  = [b for b in blobs if b["w"] <= 10]
    medium = [b for b in blobs if 10 < b["w"] <= 35]
    large  = [b for b in blobs if b["w"] > 35]

    return {
        "img_path":    img_path,
        "img_size":    (w, h),
        "white_pixels": white_pixels,
        "white_ratio":  round(white_ratio, 4),
        "bbox":         bbox,
        "blobs_small":  len(small),
        "blobs_medium": len(medium),
        "blobs_large":  len(large),
        "blobs_total":  len(blobs),
        "mean_brightness": round(float(arr.mean()), 1),
        "max_brightness":  int(arr.max()),
        "threshold":    THRESHOLD_OLED,
    }


# ── Processamento immagine ────────────────────────────────────────────────────

def process(img_path: str, out_dir: str = None) -> dict:
    """
    Applica pipeline adattiva PIL → ritorna dict con path delle versioni processate.

    Versioni generate:
      "original"  → crop centrale 70% (riduce bordi webcam)
      "threshold" → bianco/nero con soglia adattiva
      "contrast"  → contrasto estremo per evidenziare pixel OLED
      "edge"      → edge detection (Laplacian)

    Usa il preset automaticamente basato sulle stats dell'immagine originale.
    """
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ImportError:
        return {"error": "PIL non disponibile"}

    stats = analyze(img_path)
    if "error" in stats:
        return stats

    # Scegli threshold adattivo
    mean_br = stats["mean_brightness"]
    if mean_br < 5:
        # Stanza buia: soglia più bassa per catturare anche pixel semi-brillanti
        thresh_val = 120
        contrast_boost = 4.0
    elif mean_br < 20:
        thresh_val = 140
        contrast_boost = 3.0
    else:
        # Ambiente illuminato
        thresh_val = 160
        contrast_boost = 2.0

    if out_dir is None:
        out_dir = tempfile.mkdtemp(prefix="ob_proc_")
    os.makedirs(out_dir, exist_ok=True)

    base = Path(img_path).stem
    result = {"out_dir": out_dir, "stats": stats, "thresh_val": thresh_val}

    img = Image.open(img_path).convert("RGB")
    w, h = img.size

    # 1. Crop centrale 70%
    mx, my = int(w * 0.15), int(h * 0.15)
    crop = img.crop((mx, my, w - mx, h - my))
    crop2x = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    p = os.path.join(out_dir, f"{base}_crop.jpg")
    crop2x.save(p, quality=90)
    result["original"] = p

    # 2. Threshold B&W adattivo
    gray = crop.convert("L")
    # Boost contrasto prima del threshold
    gray_e = ImageEnhance.Contrast(gray).enhance(contrast_boost)
    bw = gray_e.point(lambda px: 255 if px > thresh_val else 0, "L")
    bw2x = bw.resize((bw.width * 2, bw.height * 2), Image.NEAREST)
    p = os.path.join(out_dir, f"{base}_threshold.jpg")
    bw2x.save(p, quality=95)
    result["threshold"] = p

    # 3. Contrasto estremo (grayscale)
    gray_max = ImageEnhance.Contrast(gray).enhance(contrast_boost * 1.5)
    sharp = ImageEnhance.Sharpness(gray_max).enhance(3.0)
    sharp2x = sharp.resize((sharp.width * 2, sharp.height * 2), Image.LANCZOS)
    p = os.path.join(out_dir, f"{base}_contrast.jpg")
    sharp2x.save(p, quality=90)
    result["contrast"] = p

    # 4. Edge detection
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges_e = ImageEnhance.Contrast(edges).enhance(3.0)
    edges2x = edges_e.resize((edges_e.width * 2, edges_e.height * 2), Image.LANCZOS)
    p = os.path.join(out_dir, f"{base}_edges.jpg")
    edges2x.save(p, quality=90)
    result["edge"] = p

    return result


# ── Descrizione testuale ──────────────────────────────────────────────────────

def describe(img_path: str) -> str:
    """
    Analizza un frame e genera una descrizione testuale strutturata
    comprensibile da M40 VisualJudge o MI50 vision.

    Output: stringa markdown con stats + interpretazione.
    """
    stats = analyze(img_path)
    if "error" in stats:
        return f"Errore analisi: {stats['error']}"

    lines = []
    lines.append(f"=== ANALISI FRAME: {os.path.basename(img_path)} ===")
    lines.append(f"Dimensione: {stats['img_size'][0]}x{stats['img_size'][1]}px")
    lines.append(f"Luminosità media: {stats['mean_brightness']}/255 (max: {stats['max_brightness']})")

    # Condizione di luce
    if stats["mean_brightness"] < 5:
        lines.append("Condizione: STANZA BUIA — solo OLED visibile come fonte di luce")
    elif stats["mean_brightness"] < 20:
        lines.append("Condizione: LUCE RIDOTTA — ambiente scuro con illuminazione artificiale")
    else:
        lines.append("Condizione: LUCE NORMALE")

    lines.append("")
    lines.append(f"Pixel accesi (>{THRESHOLD_OLED}/255): {stats['white_pixels']} = {stats['white_ratio']*100:.2f}%")

    if stats["bbox"]:
        b = stats["bbox"]
        lines.append(f"Zona attiva: x={b['x_min']}..{b['x_max']}, y={b['y_min']}..{b['y_max']} "
                      f"(area {b['w']}x{b['h']}px, densità {b['density']*100:.1f}%)")
    else:
        lines.append("Zona attiva: NESSUNA (display spento o non visibile)")

    lines.append("")
    lines.append(f"Blob rilevati:")
    lines.append(f"  Piccoli (≤10px)  : {stats['blobs_small']}  — puntini/pixel singoli (LED, boid dots)")
    lines.append(f"  Medi (10-35px)   : {stats['blobs_medium']} — linee/figure (testo, bordi)")
    lines.append(f"  Grandi (>35px)   : {stats['blobs_large']}  — aree (sfondo illuminato, riflessi)")

    lines.append("")
    # Interpretazione
    wr = stats["white_ratio"]
    bs = stats["blobs_small"]
    if wr < 0.001:
        lines.append("INTERPRETAZIONE: Display probabilmente SPENTO o non inquadrato.")
    elif wr < 0.01 and bs >= 2:
        lines.append(f"INTERPRETAZIONE: Display ATTIVO — {bs} punti/pixel visibili (simulazione sparse dots, boids, LED).")
    elif wr < 0.05:
        lines.append(f"INTERPRETAZIONE: Display ATTIVO — contenuto medio ({stats['blobs_total']} blob totali).")
    else:
        lines.append(f"INTERPRETAZIONE: Display ATTIVO — contenuto denso o riflessi ambientali (white_ratio={wr:.2%}).")

    return "\n".join(lines)


# ── Calibrazione ─────────────────────────────────────────────────────────────

def calibrate(out_dir: str = "/tmp/occhio_calibrate") -> dict:
    """
    Cattura frame con tutti i preset e analizza i risultati.
    Ritorna il preset migliore per le condizioni attuali + report completo.

    "Migliore" = massimo contrasto tra zona OLED e background
    (bbox density alta, noise basso, white_ratio in range [0.001, 0.30])
    """
    os.makedirs(out_dir, exist_ok=True)
    results = {}

    print(f"\n[OcchioBionico] Calibrazione in corso — {len(PRESETS)} preset...\n")

    for preset_name, preset_info in PRESETS.items():
        print(f"  Cattura preset '{preset_name}': {preset_info['desc']}")
        path = os.path.join(out_dir, f"{preset_name}.jpg")
        img_path = capture(preset_name, out_path=path)
        if img_path is None:
            results[preset_name] = {"ok": False, "error": "cattura fallita"}
            continue

        stats = analyze(img_path)
        proc  = process(img_path, out_dir=os.path.join(out_dir, preset_name))
        desc  = describe(img_path)

        # Score: vogliamo white_ratio piccolo ma > 0.0005, bbox density alta
        wr = stats["white_ratio"]
        density = stats["bbox"]["density"] if stats["bbox"] else 0
        noise   = stats["mean_brightness"]

        if wr < 0.0001:
            score = 0  # niente visibile
        elif wr > 0.30:
            score = 0.1  # troppi falsi positivi
        else:
            score = density * (1 - noise / 255)  # max density, min noise

        results[preset_name] = {
            "ok": True,
            "img": img_path,
            "stats": stats,
            "score": round(score, 4),
            "description": desc,
        }

        print(f"    white_ratio={wr:.3%}, blobs_small={stats['blobs_small']}, "
              f"density={density:.1%}, noise={noise:.1f}, score={score:.4f}")

    # Trova il preset migliore
    best = max((k for k in results if results[k].get("ok")),
               key=lambda k: results[k]["score"], default=None)

    print(f"\n[OcchioBionico] Preset migliore: {best}")
    if best:
        print(f"  → {PRESETS[best]['desc']}")

    report = {
        "best_preset": best,
        "results": results,
        "out_dir": out_dir,
    }

    report_path = os.path.join(out_dir, "calibration_report.json")
    with open(report_path, "w") as f:
        # Serializza senza le description lunghe per leggibilità
        slim = {k: {kk: vv for kk, vv in v.items() if kk != "description"}
                for k, v in results.items()}
        json.dump({"best_preset": best, "results": slim}, f, indent=2, default=str)
    print(f"[OcchioBionico] Report salvato: {report_path}")

    return report


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Occhio Bionico — pipeline visiva adattiva")
    sub = parser.add_subparsers(dest="cmd")

    # calibrate
    sub.add_parser("calibrate", help="Calibra la webcam in tutte le condizioni")

    # capture
    cap_p = sub.add_parser("capture", help="Cattura un frame")
    cap_p.add_argument("--preset", default="standard", choices=list(PRESETS.keys()))
    cap_p.add_argument("--out", default=None)
    cap_p.add_argument("--shutter", type=int, default=None, help="Shutter in microsecondi")

    # analyze
    ana_p = sub.add_parser("analyze", help="Analizza un frame esistente")
    ana_p.add_argument("img", help="Path del JPEG da analizzare")
    ana_p.add_argument("--json", action="store_true", help="Output JSON")

    # process
    proc_p = sub.add_parser("process", help="Processa un frame (genera 4 versioni)")
    proc_p.add_argument("img", help="Path del JPEG")
    proc_p.add_argument("--out", default=None, help="Directory output")

    # describe
    desc_p = sub.add_parser("describe", help="Descrizione testuale di un frame")
    desc_p.add_argument("img", help="Path del JPEG")

    # shot: capture + describe in uno
    shot_p = sub.add_parser("shot", help="Cattura e descrivi in un colpo")
    shot_p.add_argument("--preset", default="standard", choices=list(PRESETS.keys()))

    args = parser.parse_args()

    if args.cmd == "calibrate":
        calibrate()

    elif args.cmd == "capture":
        path = capture(args.preset, args.out, args.shutter)
        print(path or "ERRORE")

    elif args.cmd == "analyze":
        stats = analyze(args.img)
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            for k, v in stats.items():
                print(f"  {k}: {v}")

    elif args.cmd == "process":
        result = process(args.img, args.out)
        print(json.dumps({k: v for k, v in result.items() if k != "stats"}, indent=2))

    elif args.cmd == "describe":
        print(describe(args.img))

    elif args.cmd == "shot":
        path = capture(args.preset)
        if path:
            print(describe(path))
        else:
            print("ERRORE cattura")

    else:
        parser.print_help()
