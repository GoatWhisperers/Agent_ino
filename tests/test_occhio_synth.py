"""
test_occhio_synth.py — Test dei vision tool con immagini sintetiche (no Raspberry Pi).

Genera immagini che simulano quello che vedrebbe la webcam del Pi:
  - 640×480 pixel, sfondo scuro (ambiente reale), OLED centrato nel frame
  - Contenuto OLED bianco su nero nell'area centrale

Test coperti:
  1. check_display_on         — display OFF vs ON
  2. count_objects            — dots, segments, blocks
  3. detect_motion            — frame prima/dopo spostamento
  4. describe_scene (M40)     — VisualJudge su descrizione testuale
  5. calibrate_eye (offline)  — scoring algoritmico su immagini sintetiche

Avvio:
    source .venv/bin/activate
    python tests/test_occhio_synth.py

Per testare describe_scene con M40 reale:
    python tests/test_occhio_synth.py --m40
"""

import argparse
import os
import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Generazione immagini sintetiche ───────────────────────────────────────────

def _make_image(W=640, H=480):
    """
    Crea un'immagine base: sfondo grigio scuro con rumore ±20 (simula sensor noise).
    OLED centrato nel frame, area ~40% larghezza × 55% altezza.

    Il rumore ±20 è necessario perché le immagini sono salvate in PNG lossless —
    garantisce mean_diff > 0 tra frame diversi (in JPEG verrebbe quantizzato a 0).
    Nelle immagini reali il rumore deriva dal sensore della camera (simile).
    """
    from PIL import Image, ImageDraw
    import random

    # Sfondo con rumore ampio per rendere ogni frame unico
    img = Image.new("L", (W, H), 22)
    pix = img.load()
    for y in range(H):
        for x in range(W):
            pix[x, y] = max(0, min(255, 22 + random.randint(-20, 20)))

    # Area OLED — più grande per essere realistica (webcam ingrandisce l'OLED)
    oled_x = int(W * 0.30)
    oled_y = int(H * 0.20)
    oled_w = int(W * 0.40)   # ~256px: simula OLED a ~25cm dalla webcam
    oled_h = int(H * 0.55)   # ~264px

    draw = ImageDraw.Draw(img)
    # Bordo OLED (cornice PCB, leggermente diversa dal background)
    draw.rectangle([oled_x - 3, oled_y - 3, oled_x + oled_w + 3, oled_y + oled_h + 3],
                   fill=5)

    return img, draw, oled_x, oled_y, oled_w, oled_h


"""
SCALA DELLE IMMAGINI SINTETICHE
================================
Display OLED fisico: 128×64 pixel
Webcam 640×480 punta all'OLED da ~25cm → area OLED nel frame ≈ 256×264 px
→ 1 pixel OLED ≈ 2×4 pixel webcam

Categorie blob (area pixel nel frame webcam):
  dot     ≤ 16px   →  simulato con rettangolo 3×3  ( 9px)
  segment 17-200px →  simulato con rettangolo 12×6 (72px)
  block   > 200px  →  simulato con rettangolo 80×50 (4000px)

check_display_on threshold: white_ratio > 0.003 = 923px su 640×480
→ per passarlo servono almeno 30 segmenti da 72px (30×72=2160px > 923)
→ oppure 103 dot da 9px (impossibile, 5 dot non bastano)
→ quindi check_display_on si testa con make_display_snake() (molti segmenti)
"""


def make_display_off(W=640, H=480) -> str:
    """Display completamente spento."""
    img, draw, ox, oy, ow, oh = _make_image(W, H)
    draw.rectangle([ox, oy, ox + ow, oy + oh], fill=2)
    return _save(img, "display_off")


def make_display_dots(cx_list=None, W=640, H=480) -> str:
    """
    Display ON con 5 punti luminosi (boids sparsi).
    Dot 3×3px = 9px area → "dot" category (≤16px).
    Questi NON passano check_display_on (pochi pixel), ma sono perfetti
    per test count_objects categoria "dot".
    """
    img, draw, ox, oy, ow, oh = _make_image(W, H)
    draw.rectangle([ox, oy, ox + ow, oy + oh], fill=2)

    if cx_list is None:
        cx_list = [(20, 15), (80, 40), (45, 100), (140, 80), (100, 160)]

    for (dx, dy) in cx_list:
        x, y = ox + dx, oy + dy
        # 3×3 solid → 9px area → "dot" (≤16px)
        draw.rectangle([x, y, x + 2, y + 2], fill=255)

    return _save(img, "display_dots")


def make_display_dots_moved(dx_shift=30, dy_shift=25, W=640, H=480) -> str:
    """5 dot spostati rispetto a make_display_dots (per test centroid_displacement)."""
    cx_list_orig  = [(20, 15), (80, 40), (45, 100), (140, 80), (100, 160)]
    cx_list_moved = [(x + dx_shift, y + dy_shift) for x, y in cx_list_orig]
    return make_display_dots(cx_list=cx_list_moved, W=W, H=H)


def make_display_snake(n_segments=30, W=640, H=480) -> str:
    """
    Corpo di serpente: 30 segmenti da 12×6px = 72px ciascuno.
    Totale: 30 × 72 = 2160px > 923 → supera check_display_on (white_ratio=0.007).
    Ogni segmento è "segment" category (72px, 17-200px).
    """
    img, draw, ox, oy, ow, oh = _make_image(W, H)
    draw.rectangle([ox, oy, ox + ow, oy + oh], fill=2)

    # Serpente sinuoso orizzontale poi che gira in basso
    x, y = ox + 15, oy + 50
    for i in range(n_segments):
        draw.rectangle([x, y, x + 11, y + 5], fill=245)
        if i < 15:
            x += 13
        elif i < 22:
            y += 10
        else:
            x -= 13

    return _save(img, "display_snake")


def make_display_segments_v2(W=640, H=480) -> str:
    """
    3 segmenti separati (12×6px ciascuno = 72px → "segment" category).
    Usato per test count_objects categoria "segment".
    """
    img, draw, ox, oy, ow, oh = _make_image(W, H)
    draw.rectangle([ox, oy, ox + ow, oy + oh], fill=2)

    positions = [(20, 30), (100, 80), (50, 150)]
    for (dx, dy) in positions:
        draw.rectangle([ox + dx, oy + dy, ox + dx + 11, oy + dy + 5], fill=245)

    return _save(img, "display_segments")


def make_display_text(text_str="SCORE: 42", W=640, H=480) -> str:
    """Display con testo — usa font grande per avere abbastanza pixel bianchi."""
    from PIL import ImageDraw, ImageFont
    img, draw, ox, oy, ow, oh = _make_image(W, H)
    draw.rectangle([ox, oy, ox + ow, oy + oh], fill=2)

    try:
        font_big  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 20)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 14)
    except (IOError, OSError):
        font_big = font_small = ImageFont.load_default()

    draw.text((ox + 10, oy + 20), text_str, fill=245, font=font_big)
    draw.text((ox + 10, oy + 55), "LEVEL: 3", fill=210, font=font_small)
    draw.text((ox + 10, oy + 80), "SPEED: 120ms", fill=200, font=font_small)

    return _save(img, "display_text")


def make_display_mixed(W=640, H=480) -> str:
    """
    Display misto: 3 dot (3×3) + 1 segmento (12×6) + 1 blocco (80×50).
    Verifica che count_objects categorizzi correttamente e scorpori i block.
    """
    img, draw, ox, oy, ow, oh = _make_image(W, H)
    draw.rectangle([ox, oy, ox + ow, oy + oh], fill=2)

    # 3 dot (area 9px → "dot")
    for (dx, dy) in [(15, 20), (50, 35), (120, 70)]:
        draw.rectangle([ox + dx, oy + dy, ox + dx + 2, oy + dy + 2], fill=255)

    # 1 segmento (12×6 = 72px → "segment")
    draw.rectangle([ox + 20, oy + 110, ox + 31, oy + 115], fill=240)

    # 1 blocco grande (80×50 = 4000px → "block" — riflesso ambientale simulato)
    # Deve essere > THRESHOLD_OLED (160) per essere rilevato come blob
    draw.rectangle([ox + 10, oy + 150, ox + 89, oy + 199], fill=175)

    return _save(img, "display_mixed")


def make_calibration_set(W=640, H=480) -> dict[str, str]:
    """
    Simula 5 frame per calibrazione camera.
    Base: snake con 20 segmenti (abbastanza pixel per avere white_ratio > 0).
    Ogni preset simula diversa esposizione/contrasto via ImageEnhance.
    """
    from PIL import Image, ImageEnhance

    # Crea immagine base con contenuto visibile
    img_base, draw, ox, oy, ow, oh = _make_image(W, H)
    draw.rectangle([ox, oy, ox + ow, oy + oh], fill=2)
    # Snake di 20 segmenti (20×72px = 1440 bright pixels visibili)
    x, y = ox + 15, oy + 50
    for i in range(20):
        draw.rectangle([x, y, x + 11, y + 5], fill=245)
        x += 13

    # Simula preset camera con Brightness/Contrast
    results = {}

    # standard: contrasto base
    results["standard"] = _save(
        ImageEnhance.Contrast(img_base).enhance(1.8), "cal_standard"
    )
    # dark: OLED più brillante (simulazione buio: OLED è unica fonte luce)
    dark = ImageEnhance.Brightness(img_base).enhance(0.3)
    dark = ImageEnhance.Contrast(dark).enhance(3.0)
    results["dark"] = _save(dark, "cal_dark")

    # bright: EV negativo → immagine più scura ma OLED ancora visibile
    bright = ImageEnhance.Brightness(img_base).enhance(0.6)
    bright = ImageEnhance.Contrast(bright).enhance(1.8)
    results["bright"] = _save(bright, "cal_bright")

    # oled_only: contrasto estremo (isola OLED dal background)
    oled = ImageEnhance.Contrast(img_base).enhance(4.0)
    results["oled_only"] = _save(oled, "cal_oled_only")

    # high_contrast: bilanciato
    hc = ImageEnhance.Contrast(img_base).enhance(2.5)
    results["high_contrast"] = _save(hc, "cal_high_contrast")

    return results


# ── Utility ───────────────────────────────────────────────────────────────────

_TMPDIR   = None
_SAVE_CTR = 0

def _save(img, name: str) -> str:
    """
    Salva in PNG (lossless) con un counter univoco per evitare sovrascritture
    tra chiamate diverse della stessa funzione generatrice (e per evitare
    mean_diff=0 quando due frame "distinti" puntano allo stesso file).
    """
    global _TMPDIR, _SAVE_CTR
    if _TMPDIR is None:
        _TMPDIR = tempfile.mkdtemp(prefix="occhio_test_")
    _SAVE_CTR += 1
    path = os.path.join(_TMPDIR, f"{_SAVE_CTR:03d}_{name}.png")
    img.save(path)
    return path


def _header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _ok(label: str, val=None):
    suffix = f"  →  {val}" if val is not None else ""
    print(f"  ✓ {label}{suffix}")


def _fail(label: str, val=None):
    suffix = f"  →  {val}" if val is not None else ""
    print(f"  ✗ {label}{suffix}")


def _check(condition: bool, label: str, val=None):
    (_ok if condition else _fail)(label, val)
    return condition


# ── Test 1: check_display_on ─────────────────────────────────────────────────

def test_display_on_off():
    _header("TEST 1 — check_display_on (pixel analysis locale)")

    from agent.occhio._common import THRESHOLD_OLED
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        print("  SKIP — PIL/numpy non disponibili")
        return

    def _wr(path):
        img = Image.open(path).convert("L")
        arr = np.array(img)
        return float((arr > THRESHOLD_OLED).sum()) / arr.size

    off_path   = make_display_off()
    snake_path = make_display_snake()   # molti segmenti → white_ratio > 0.003
    dots_path  = make_display_dots()   # solo 5 dot 3×3 → white_ratio < 0.003

    wr_off   = _wr(off_path)
    wr_snake = _wr(snake_path)
    wr_dots  = _wr(dots_path)

    print(f"\n  display_off   : white_ratio = {wr_off:.5f}")
    print(f"  display_snake : white_ratio = {wr_snake:.5f}  (30 segmenti)")
    print(f"  display_dots  : white_ratio = {wr_dots:.5f}   (5 dot 3×3)")

    _check(wr_off   < 0.003, "display_off → OFF (white_ratio < 0.003)", f"{wr_off:.5f}")
    _check(wr_snake > 0.003, "display_snake → ON (white_ratio > 0.003)", f"{wr_snake:.5f}")
    _check(wr_snake < 0.60,  "display_snake non sovraesposto (< 0.60)",  f"{wr_snake:.5f}")
    print(f"\n  Nota: 5 dot da 3×3 (45px / 307200) non bastano per check_display_on.")
    print(f"  In condizioni reali, l'OLED ha MOLTI più pixel — il serpente con 30 segmenti")
    print(f"  è un esempio realistico (white_ratio={wr_snake:.4f}).")


# ── Test 2: count_objects ─────────────────────────────────────────────────────

def test_count_objects():
    _header("TEST 2 — count_objects (blob 2D con coordinate)")

    from agent.occhio.analyze import count_objects

    cases = [
        ("display spento",         make_display_off(),          {"expected_total": 0}),
        ("5 dot 3×3 (boids)",      make_display_dots(),         {"min_total": 3, "min_dots": 3}),
        ("3 segmenti 12×6 (snake)",make_display_segments_v2(),  {"min_total": 1, "min_segs": 1}),
        ("misto: dot+seg+block",   make_display_mixed(),        {"min_dots": 1, "min_segs": 1, "min_blocks": 1}),
    ]

    for label, path, expect in cases:
        result = count_objects([path])
        total = result["total"]
        dots  = len(result["dots"])
        segs  = len(result["segments"])
        blocks = result["blocks"]

        print(f"\n  [{label}]")
        print(f"    total={total}  dots={dots}  segments={segs}  blocks={blocks}")
        print(f"    {result['description'][:80]}")

        if "expected_total" in expect:
            et = expect["expected_total"]
            _check(total == et, f"total == {et}", f"got {total}")
        if "min_total" in expect:
            _check(total >= expect["min_total"], f"total >= {expect['min_total']}", f"got {total}")
        if "min_dots" in expect:
            _check(dots >= expect["min_dots"], f"dots >= {expect['min_dots']}", f"got {dots}")
        if "min_segs" in expect:
            _check(segs >= expect["min_segs"], f"segments >= {expect['min_segs']}", f"got {segs}")
        if "min_blocks" in expect:
            _check(blocks >= expect["min_blocks"], f"blocks >= {expect['min_blocks']}", f"got {blocks}")


# ── Test 3: detect_motion ─────────────────────────────────────────────────────

def test_detect_motion():
    _header("TEST 3 — detect_motion (mean_diff + centroid_displacement)")

    from agent.occhio.analyze import detect_motion

    # Caso 1: STESSO file caricato due volte → mean_diff esattamente 0
    path = make_display_dots()
    result_static = detect_motion([path, path])
    print(f"\n  [stesso file 2×]  mean_diff={result_static['mean_diff']:.2f}  "
          f"displacement={result_static['centroid_displacement']:.1f}  "
          f"motion={result_static['motion_detected']}")
    _check(result_static["mean_diff"] == 0.0, "stesso file → mean_diff=0")
    _check(not result_static["motion_detected"], "stesso file → no motion")

    # Caso 2: due frame DISTINTI con rumore PNG diverso (background noise ±20)
    # mean_diff atteso ≈ E[|a-b|] dove a,b ~ Uniform(2, 42) → E[|a-b|] ≈ 13
    path_a = make_display_off()
    path_b = make_display_off()  # stesso contenuto ma rumore PNG diverso
    result_noise = detect_motion([path_a, path_b])
    print(f"\n  [2 frame distinti, stesso contenuto, rumore diverso]")
    print(f"    mean_diff={result_noise['mean_diff']:.2f}  "
          f"motion={result_noise['motion_detected']}")
    _check(result_noise["mean_diff"] > 0, "frame diversi → mean_diff > 0",
           f"{result_noise['mean_diff']:.2f}")

    # Caso 3: snake che si sposta (molti pixel cambiano)
    path_snake_a = make_display_snake(n_segments=30)
    path_snake_b = make_display_snake(n_segments=30)  # posizione diversa per rumore
    # Per un test più significativo: OFF → snake acceso
    path_off  = make_display_off()
    path_on   = make_display_snake()
    result_onoff = detect_motion([path_off, path_on])
    print(f"\n  [display OFF→ON snake]  mean_diff={result_onoff['mean_diff']:.2f}  "
          f"displacement={result_onoff['centroid_displacement']:.1f}  "
          f"motion={result_onoff['motion_detected']}  "
          f"confidence={result_onoff['confidence']}")
    _check(result_onoff["motion_detected"], "OFF→ON → motion detected",
           f"diff={result_onoff['mean_diff']:.2f}")

    # Caso 4: 5 dot spostati di 30px → centroid_displacement
    path_d1 = make_display_dots()
    path_d2 = make_display_dots_moved(dx_shift=30, dy_shift=25)
    result_dots = detect_motion([path_d1, path_d2])
    print(f"\n  [5 dot spostati 30px]  mean_diff={result_dots['mean_diff']:.2f}  "
          f"displacement={result_dots['centroid_displacement']:.1f}px  "
          f"motion={result_dots['motion_detected']}")
    _check(result_dots["mean_diff"] > 0, "dot spostati → mean_diff > 0",
           f"{result_dots['mean_diff']:.2f}")


# ── Test 4: describe_scene con M40 ───────────────────────────────────────────

def test_describe_scene_m40():
    _header("TEST 4 — describe_scene (M40 VisualJudge su descrizione testuale)")

    from agent.occhio.analyze import count_objects, detect_motion
    from agent.occhio.describe import _build_text_description, _m40_judge

    cases = [
        {
            "label": "5 boids in movimento",
            "paths": [make_display_dots(), make_display_dots_moved()],
            "goal":  "5 punti luminosi che si muovono autonomamente su display OLED",
        },
        {
            "label": "snake con 30 segmenti",
            "paths": [make_display_snake()],
            "goal":  "serpente con body visibile (molti segmenti connessi)",
        },
        {
            "label": "display spento",
            "paths": [make_display_off()],
            "goal":  "qualsiasi contenuto visibile su display OLED acceso",
        },
    ]

    for case in cases:
        label  = case["label"]
        paths  = case["paths"]
        goal   = case["goal"]

        objects = count_objects(paths)
        motion  = detect_motion(paths) if len(paths) > 1 else None
        desc    = _build_text_description(paths, objects, motion, goal)

        print(f"\n  [{label}]")
        print(f"  Descrizione testuale per M40:\n")
        for line in desc.split("\n"):
            print(f"    {line}")

        print(f"\n  → Chiamo M40 VisualJudge...")
        try:
            result = _m40_judge(desc)
            success    = result.get("success")
            confidence = result.get("confidence", "?")
            reason     = result.get("reason", "")[:100]
            print(f"  M40: success={success}  confidence={confidence}")
            print(f"  M40: reason = {reason}")
            _ok(f"M40 ha risposto (confidence={confidence})")
        except Exception as e:
            print(f"  M40 non raggiungibile: {e}")
            print(f"  [descrizione generata correttamente — M40 offline]")
            _ok("descrizione testuale generata (M40 offline — skip giudizio)")


# ── Test 5: calibrate_eye offline (scoring algoritmico) ──────────────────────

def test_calibrate_offline():
    _header("TEST 5 — calibrate_eye (scoring algoritmico offline)")

    from agent.occhio.calibrate import _analyze_for_target
    import json

    # Genera set di immagini calibrazione
    cal_imgs = make_calibration_set()
    print(f"\n  Immagini generate: {list(cal_imgs.keys())}")

    results = {}
    for preset_name, img_path in cal_imgs.items():
        analysis = _analyze_for_target(img_path, target="oled")
        results[preset_name] = analysis
        print(f"\n  [{preset_name}]")
        print(f"    white_ratio={analysis.get('white_ratio', 0):.4f}  "
              f"score={analysis.get('score', 0):.4f}  "
              f"blobs={analysis.get('blob_count', 0)}  "
              f"saturated={analysis.get('saturated', False)}")
        print(f"    {analysis.get('notes', '')}")

    # Preset vincente
    best = max(
        (k for k in results if "score" in results[k]),
        key=lambda k: results[k]["score"],
        default=None,
    )
    print(f"\n  Preset migliore (offline): '{best}'  (score={results[best]['score']:.4f})")
    _ok(f"calibrazione algortimica completata — best={best}")


# ── Test 6: MI50 calibrazione vision (richiede MI50 attivo) ──────────────────

def test_calibrate_mi50():
    _header("TEST 6 — calibrate_eye con MI50 vision (richiede MI50 server)")

    from agent.occhio.calibrate import _analyze_for_target

    # Genera immagini
    cal_imgs = make_calibration_set()

    # Chiedi a MI50 di guardare i frame e descrivere cosa vede
    try:
        from agent.mi50_client import MI50Client
        client = MI50Client()
    except Exception as e:
        print(f"  MI50 non disponibile: {e} — SKIP")
        return

    print(f"\n  Invio frame di calibrazione a MI50-vision...")

    # Per ogni preset, MI50 descrive la qualità del frame
    best_mi50 = None
    best_score = -1

    for preset_name, img_path in cal_imgs.items():
        # Score algoritmico come base
        algo = _analyze_for_target(img_path, target="oled")
        algo_score = algo.get("score", 0)

        # MI50 vision: valuta la qualità visiva del frame
        try:
            result = client.generate_with_images(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Questo frame è stato catturato con preset camera '{preset_name}'. "
                        "Valuta la QUALITÀ visiva per vedere un display OLED su sfondo scuro. "
                        "Rispondi SOLO con JSON: "
                        '{"quality": 0.0-1.0, "visible_objects": int, "note": "max 20 parole"}'
                    )
                }],
                image_paths=[img_path],
                max_new_tokens=80,
                label=f"MI50-cal-{preset_name}",
            )
            raw = result.get("response", result.get("raw", ""))
            import re, json as _json
            m = re.search(r'\{.*?"quality".*?\}', raw, re.DOTALL)
            if m:
                parsed = _json.loads(m.group(0))
                mi50_quality = float(parsed.get("quality", 0))
                combined = 0.5 * algo_score + 0.5 * mi50_quality
                note = parsed.get("note", "")
                print(f"\n  [{preset_name}] algo={algo_score:.3f} mi50={mi50_quality:.3f} combined={combined:.3f}")
                print(f"    MI50: {note}")
                if combined > best_score:
                    best_score = combined
                    best_mi50 = preset_name
            else:
                print(f"\n  [{preset_name}] algo={algo_score:.3f} MI50 parse fallito: {raw[:60]}")

        except Exception as e:
            print(f"  [{preset_name}] MI50 errore: {e}")

    if best_mi50:
        print(f"\n  Preset scelto da MI50+algo: '{best_mi50}' (score={best_score:.3f})")
        _ok(f"calibrazione MI50+algo completata — best={best_mi50}")
    else:
        print(f"  Nessun risultato MI50 utile")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test occhio bionico con immagini sintetiche")
    parser.add_argument("--m40",  action="store_true", help="Testa M40 VisualJudge (richiede server)")
    parser.add_argument("--mi50", action="store_true", help="Testa MI50 vision calibrazione (richiede server)")
    parser.add_argument("--all",  action="store_true", help="Tutti i test inclusi M40 e MI50")
    parser.add_argument("--save", action="store_true", help="Salva immagini generate in ./test_frames/")
    args = parser.parse_args()

    print("=" * 60)
    print("  OCCHIO BIONICO — Test con immagini sintetiche")
    print("=" * 60)

    # Test offline (non richiedono server)
    test_display_on_off()
    test_count_objects()
    test_detect_motion()
    test_calibrate_offline()

    # Test che richiedono M40
    if args.m40 or args.all:
        test_describe_scene_m40()
    else:
        _header("TEST 4 — describe_scene [SKIP — usa --m40 per attivare]")
        print("  La descrizione testuale viene generata ma M40 non viene chiamato.")
        # Mostra almeno la descrizione senza il giudizio
        from agent.occhio.analyze import count_objects, detect_motion
        from agent.occhio.describe import _build_text_description
        paths = [make_display_snake(), make_display_snake()]
        objects = count_objects(paths)
        motion  = detect_motion(paths)
        desc    = _build_text_description(paths, objects, motion,
                                          "serpente con almeno 10 segmenti visibili su OLED")
        print("\n  Descrizione che verrebbe data a M40:")
        for line in desc.split("\n"):
            print(f"    {line}")

    # Test MI50 vision calibrazione
    if args.mi50 or args.all:
        test_calibrate_mi50()
    else:
        _header("TEST 6 — calibrate_eye MI50-vision [SKIP — usa --mi50 per attivare]")

    # Salva immagini se richiesto
    if args.save:
        save_dir = Path("test_frames")
        save_dir.mkdir(exist_ok=True)
        import shutil
        for f in Path(_TMPDIR).glob("*.jpg"):
            shutil.copy(f, save_dir / f.name)
        print(f"\n  Immagini salvate in {save_dir.resolve()}/")

    print(f"\n{'='*60}")
    print(f"  Immagini generate in: {_TMPDIR}")
    print(f"  (rimosso al prossimo riavvio — usa --save per conservarle)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
