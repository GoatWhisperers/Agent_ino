"""
Evaluator — valuta se il task Arduino è stato completato.

Due strategie di valutazione visiva:

  evaluate_visual_opencv(task, frame_paths, serial_output, expected_events)
      Pipeline deterministica:
        1. PIL: genera 3 versioni immagine (originale crop, threshold B&W, edge detection)
        2. PIL: analisi pixel → descrizione testuale strutturata (blob, dimensioni, posizioni)
        3. M40: giudica se la descrizione corrisponde al comportamento atteso
      Vantaggi: non dipende dallo sfondo ambientale, M40 è veloce, risultato ripetibile.

  evaluate_visual(task, frame_paths, serial_output)
      Pipeline MI50-vision (legacy): pre-processa i frame e li invia a MI50 multimodal.
      Usata come fallback se opencv_pipeline restituisce risultato ambiguo.

  evaluate(task, serial_output, code)
      Valutazione testuale pura via MI50 (serial output + codice).
"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, "/home/lele/codex-openai/programmatore_di_arduini")

from agent.mi50_client import MI50Client  # noqa: E402
from agent.m40_client import M40Client    # noqa: E402

_EVAL_SYSTEM = """
Sei un giudice tecnico per progetti Arduino.
Il tuo output deve essere ESCLUSIVAMENTE un oggetto JSON valido. Nessun testo prima o dopo.

STRUTTURA OBBLIGATORIA:
{"success":true,"reason":"...","suggestions":""}

- success: true se il task è completato, false altrimenti
- reason: stringa, spiegazione concisa della valutazione
- suggestions: stringa, cosa cambiare se success=false, stringa vuota se success=true

Rispondi SOLO con il JSON. Zero testo aggiuntivo.
"""

_M40_VISUAL_JUDGE_SYSTEM = """
Sei un giudice tecnico. Ricevi la descrizione visiva di un display OLED e devi valutare
se quello che è visibile corrisponde al comportamento atteso del programma.

Rispondi ESCLUSIVAMENTE con JSON:
{"success": true/false, "reason": "spiegazione concisa", "suggestions": ""}

Nessun testo prima o dopo il JSON.
"""


def _safe_json(text: str, fallback: dict) -> dict:
    m = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    for m in reversed(list(re.finditer(r"\{.*?\}", text, re.DOTALL))):
        try:
            r = json.loads(m.group(0))
            if isinstance(r, dict):
                return r
        except (json.JSONDecodeError, ValueError):
            pass
    return fallback


# ── Pipeline OpenCV/PIL: analisi pixel → descrizione testuale ──────────────────

def _analyze_frame_pixels(img_gray) -> dict:
    """
    Analisi pixel su immagine grayscale PIL.
    Trova blob bianchi: dimensione e posizione → classifica in palline/mattoncini/testo.
    Ritorna dict con statistiche.
    """
    import numpy as np

    arr = np.array(img_gray)
    h, w = arr.shape

    # Threshold: pixel > 180 considerati "accesi" (pixel OLED bianchi)
    binary = (arr > 180).astype(np.uint8)
    white_pixels = int(binary.sum())
    total_pixels = h * w
    white_ratio = white_pixels / total_pixels

    # Analisi colonne e righe per trovare zone attive
    col_sums = binary.sum(axis=0)  # pixel bianchi per colonna
    row_sums = binary.sum(axis=1)  # pixel bianchi per riga

    # Zone attive: colonne/righe con almeno 1 pixel bianco
    active_cols = int((col_sums > 0).sum())
    active_rows = int((row_sums > 0).sum())

    # Distribuzione orizzontale: metà sinistra vs destra
    mid = w // 2
    left_white  = int(binary[:, :mid].sum())
    right_white = int(binary[:, mid:].sum())

    # Stima blob: run-length encoding semplice per trovare cluster di pixel bianchi
    blobs = []
    # Scan per righe: trova segmenti contigui
    for y in range(0, h, 4):  # sample ogni 4 righe per velocità
        row = binary[y]
        in_blob = False
        bstart = 0
        for x in range(w):
            if row[x] and not in_blob:
                in_blob = True
                bstart = x
            elif not row[x] and in_blob:
                in_blob = False
                blen = x - bstart
                if blen >= 2:
                    blobs.append({"x": bstart, "y": y, "w": blen})
        if in_blob:
            blobs.append({"x": bstart, "y": y, "w": w - bstart})

    # Classifica blob per larghezza:
    # piccoli (w <= 10): possibili palline
    # medi (10 < w <= 35): possibili mattoncini
    # grandi (w > 35): possibili aree grandi
    small_blobs  = [b for b in blobs if b["w"] <= 10]
    medium_blobs = [b for b in blobs if 10 < b["w"] <= 35]
    large_blobs  = [b for b in blobs if b["w"] > 35]

    return {
        "white_pixels": white_pixels,
        "white_ratio": round(white_ratio, 4),
        "active_cols": active_cols,
        "active_rows": active_rows,
        "left_white": left_white,
        "right_white": right_white,
        "small_blobs_count": len(small_blobs),   # palline candidate
        "medium_blobs_count": len(medium_blobs),  # mattoncini candidati
        "large_blobs_count": len(large_blobs),
        "total_blobs": len(blobs),
    }


def _preprocess_multi(frame_paths: list) -> tuple[list, list, list]:
    """
    Genera 3 versioni di ogni frame:
    1. Crop centrale 60% upscale 2x (per MI50-vision legacy)
    2. Grayscale + threshold B&W (per analisi pixel)
    3. Edge detection (per analisi struttura)

    Ritorna:
      (cropped_paths, threshold_paths, edge_paths, tmpfiles)
    """
    try:
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError:
        return frame_paths, [], [], []

    cropped_paths   = []
    threshold_paths = []
    edge_paths      = []
    tmpfiles        = []

    for fpath in frame_paths:
        try:
            img = Image.open(fpath).convert("RGB")
            w, h = img.size

            # --- Versione 1: crop centrale + upscale (legacy MI50) ---
            mx, my = w // 5, h // 5
            crop = img.crop((mx, my, w - mx, h - my))
            cw, ch = crop.size
            up = crop.resize((cw * 2, ch * 2), Image.LANCZOS)
            up = ImageEnhance.Contrast(up).enhance(2.0)
            fd, p = tempfile.mkstemp(suffix=".jpg", prefix="oled_crop_")
            os.close(fd)
            up.save(p, "JPEG", quality=95)
            cropped_paths.append(p)
            tmpfiles.append(p)

            # --- Versione 2: grayscale + threshold netto ---
            gray = img.convert("L")
            # Boost contrasto forte prima del threshold
            gray = ImageEnhance.Contrast(gray).enhance(3.0)
            # Threshold: pixel > 160 → bianco, resto → nero
            thresh = gray.point(lambda px: 255 if px > 160 else 0, "L")
            # Upscale per visibilità
            tw, th = thresh.size
            thresh_up = thresh.resize((tw * 2, th * 2), Image.NEAREST)
            fd, p = tempfile.mkstemp(suffix=".jpg", prefix="oled_thresh_")
            os.close(fd)
            thresh_up.save(p, "JPEG", quality=95)
            threshold_paths.append(p)
            tmpfiles.append(p)

            # --- Versione 3: edge detection ---
            gray2 = img.convert("L")
            gray2 = ImageEnhance.Contrast(gray2).enhance(2.0)
            edges = gray2.filter(ImageFilter.FIND_EDGES)
            edges = ImageEnhance.Contrast(edges).enhance(3.0)
            ew, eh = edges.size
            edges_up = edges.resize((ew * 2, eh * 2), Image.LANCZOS)
            fd, p = tempfile.mkstemp(suffix=".jpg", prefix="oled_edge_")
            os.close(fd)
            edges_up.save(p, "JPEG", quality=95)
            edge_paths.append(p)
            tmpfiles.append(p)

        except Exception as e:
            cropped_paths.append(fpath)
            if not threshold_paths or len(threshold_paths) < len(cropped_paths):
                threshold_paths.append(fpath)
            if not edge_paths or len(edge_paths) < len(cropped_paths):
                edge_paths.append(fpath)

    return cropped_paths, threshold_paths, edge_paths, tmpfiles


def _build_pixel_description(frame_paths: list) -> str:
    """
    Analizza i frame originali pixel per pixel e genera una descrizione testuale
    strutturata per M40.
    """
    try:
        from PIL import Image, ImageEnhance
    except ImportError:
        return "Analisi pixel non disponibile (PIL mancante)."

    descriptions = []
    for i, fpath in enumerate(frame_paths):
        try:
            img = Image.open(fpath).convert("L")
            w, h = img.size

            # Crop centro (dove c'è il display)
            mx, my = w // 5, h // 5
            crop = img.crop((mx, my, w - mx, h - my))
            crop = ImageEnhance.Contrast(crop).enhance(3.0)

            stats = _analyze_frame_pixels(crop)

            desc = (
                f"Frame {i+1}: "
                f"pixel_bianchi={stats['white_pixels']} ({stats['white_ratio']*100:.1f}%), "
                f"zona_sinistra={stats['left_white']}px, zona_destra={stats['right_white']}px, "
                f"blob_piccoli(≤10px, palline candidate)={stats['small_blobs_count']}, "
                f"blob_medi(10-35px, mattoncini candidati)={stats['medium_blobs_count']}, "
                f"blob_grandi={stats['large_blobs_count']}, "
                f"colonne_attive={stats['active_cols']}, righe_attive={stats['active_rows']}"
            )
            descriptions.append(desc)
        except Exception as e:
            descriptions.append(f"Frame {i+1}: errore analisi ({e})")

    return "\n".join(descriptions)


def _frames_differ(frame_paths: list) -> bool:
    """Verifica se i frame sono diversi (animazione in corso)."""
    try:
        from PIL import Image
        import numpy as np
        if len(frame_paths) < 2:
            return False
        imgs = [np.array(Image.open(p).convert("L")) for p in frame_paths[:3]]
        diffs = [int(abs(imgs[i].astype(int) - imgs[i-1].astype(int)).mean())
                 for i in range(1, len(imgs))]
        return any(d > 2 for d in diffs)  # diff media > 2 livelli di grigio = animazione
    except Exception:
        return False


# ── Legacy: preprocess solo per MI50 vision ────────────────────────────────────

def _preprocess_frames(frame_paths: list) -> tuple[list, list]:
    """Legacy: crop + upscale + contrasto per MI50-vision."""
    cropped, _, _, tmpfiles = _preprocess_multi(frame_paths)
    return cropped, tmpfiles


# ── Evaluator class ────────────────────────────────────────────────────────────

class Evaluator:
    def __init__(self):
        self.mi50 = MI50Client.get()
        self.m40  = M40Client()

    def evaluate(self, task: str, serial_output: str, code: str = "") -> dict:
        """
        Valutazione testuale via MI50: serial output + codice.
        """
        user_parts = [
            f"Task richiesto: {task}",
            "",
            "=== OUTPUT SERIALE ===",
            serial_output if serial_output else "(nessun output seriale)",
        ]
        if code:
            user_parts += ["", "=== CODICE CARICATO ===", code]

        messages = [
            {"role": "system", "content": _EVAL_SYSTEM},
            {"role": "user",   "content": "\n".join(user_parts)},
        ]

        result = self.mi50.generate(messages, max_new_tokens=8192, label="MI50→Evaluator")
        parsed = _safe_json(result["response"], fallback={
            "success": False, "reason": result["response"], "suggestions": "",
        })
        success_raw = parsed.get("success", False)
        success = success_raw.lower() in ("true","1","yes","sì") if isinstance(success_raw, str) else bool(success_raw)
        return {"success": success, "reason": parsed.get("reason",""),
                "suggestions": parsed.get("suggestions",""), "thinking": result["thinking"]}

    def evaluate_serial_events(
        self,
        task: str,
        serial_output: str,
        expected_events: list[str],
    ) -> dict:
        """
        SERIAL-FIRST: verifica rapida se gli eventi attesi sono presenti nel serial output.
        Usa M40 (veloce) invece di MI50.

        expected_events: lista di stringhe da cercare (es. ["HIT", "BREAK"])
        Ritorna {"success": bool, "reason": str, "matched": list[str]}
        """
        if not serial_output or not serial_output.strip():
            return {
                "success": False,
                "reason": "Nessun output seriale ricevuto — impossibile verificare eventi.",
                "matched": [],
            }

        matched = [ev for ev in expected_events if ev in serial_output]

        if len(matched) >= 1:
            return {
                "success": True,
                "reason": f"Serial output contiene eventi attesi: {matched}. Il codice funziona.",
                "matched": matched,
            }

        # Se non evidenti, chiedi a M40 di valutare
        prompt = (
            f"Task: {task}\n\n"
            f"Output seriale ricevuto:\n{serial_output[:500]}\n\n"
            f"Eventi attesi: {expected_events}\n\n"
            f"Il serial output indica che il programma funziona correttamente?\n"
            f"Rispondi SOLO con JSON: {{\"success\": true/false, \"reason\": \"...\", \"suggestions\": \"\"}}"
        )
        result = self.m40.generate(
            [{"role": "system", "content": _M40_VISUAL_JUDGE_SYSTEM},
             {"role": "user",   "content": prompt}],
            max_tokens=200, label="M40→SerialJudge"
        )
        parsed = _safe_json(result["response"], fallback={
            "success": False, "reason": result["response"], "suggestions": "",
        })
        success_raw = parsed.get("success", False)
        success = success_raw.lower() in ("true","1","yes","sì") if isinstance(success_raw, str) else bool(success_raw)
        return {"success": success, "reason": parsed.get("reason",""), "matched": matched}

    def evaluate_visual_opencv(
        self,
        task: str,
        frame_paths: list,
        serial_output: str = "",
        expected_events: list[str] = None,
    ) -> dict:
        """
        Pipeline visiva principale: serial-first → observer (M40+MI50 vision) → M40 judge.

        Flusso:
          0. Serial-first: se eventi attesi trovati nel serial → success immediato
          1. observe_display: M40 mini-loop con MI50 vision in parallelo
             → cattura frame freschi, view_frame, detect_motion, count_objects
          2. Se observer.success_hint=True → M40 conferma vs task description → done
          3. Se observer.success_hint=False → M40 giudica → fallback MI50-vision se incerto
        """
        # --- Step 0: serial events fast-path ---
        if expected_events and serial_output and serial_output.strip():
            matched = [ev for ev in expected_events if ev in serial_output]
            if matched:
                return {
                    "success": True,
                    "reason": f"Serial output contiene eventi attesi: {matched}. [serial-first]",
                    "suggestions": "", "thinking": "", "pipeline": "serial-first",
                }

        # --- Step 1: observer sub-agent ---
        print("\n  [Evaluator] Observer sub-agent (M40 + MI50 vision)...", flush=True)
        try:
            from agent.occhio.observer import observe_display
            obs = observe_display(goal=task, max_steps=8)
        except Exception as e:
            print(f"\n  [Evaluator] Observer fallito: {e} → pixel analysis fallback", flush=True)
            obs = None

        # --- Step 2: observer success_hint=True → M40 conferma ---
        if obs and obs.get("display_on") and obs.get("success_hint"):
            obs_description = (
                f"Descrizione visiva: {obs.get('description','')}\n"
                f"Oggetti rilevati: {obs.get('objects_total', 0)} "
                f"(dots={len(obs.get('dots') or [])}, segments={len(obs.get('segments') or [])})\n"
                f"Movimento: {'SÌ' if obs.get('motion_detected') else 'NO'} "
                f"(confidence={obs.get('motion_confidence','?')}, "
                f"displacement={obs.get('centroid_displacement',0):.1f}px)\n"
                f"Testo: {obs.get('text') or 'nessuno'}\n"
                f"success_hint observer: True"
            )
            if serial_output and serial_output.strip():
                obs_description += f"\nSerial: {serial_output[:200]}"

            prompt = (
                f"Task: {task}\n\n"
                f"=== REPORT OBSERVER ===\n{obs_description}\n\n"
                f"L'observer indica success_hint=True. Confermi che il task è completato?\n"
                f"Rispondi SOLO JSON: {{\"success\": true/false, \"reason\": \"...\", \"suggestions\": \"\"}}"
            )
            m40_result = self.m40.generate(
                [{"role": "system", "content": _M40_VISUAL_JUDGE_SYSTEM},
                 {"role": "user",   "content": prompt}],
                max_tokens=200, label="M40→ObserverJudge"
            )
            parsed = _safe_json(m40_result["response"], {"success": True, "reason": obs.get("reason",""), "suggestions": ""})
            success_raw = parsed.get("success", True)
            success = success_raw.lower() in ("true","1","yes","sì") if isinstance(success_raw, str) else bool(success_raw)
            if success:
                return {
                    "success": True,
                    "reason": parsed.get("reason", obs.get("reason", "")),
                    "suggestions": "",
                    "thinking": f"Observer: {obs.get('description','')[:150]}",
                    "pipeline": "observer+m40",
                }

        # --- Step 3: observer fallito o success_hint=False → M40 giudica il report ---
        if obs:
            obs_description = (
                f"Descrizione visiva: {obs.get('description', 'N/A')}\n"
                f"Display acceso: {obs.get('display_on')}\n"
                f"Oggetti: {obs.get('objects_total', 0)}\n"
                f"Movimento: {obs.get('motion_detected')} ({obs.get('motion_confidence','?')})\n"
                f"Testo OCR: {obs.get('text') or 'nessuno'}\n"
                f"Observer reason: {obs.get('reason','')}"
            )
            if serial_output and serial_output.strip():
                obs_description += f"\nSerial: {serial_output[:200]}"

            prompt = (
                f"Task: {task}\n\n"
                f"=== REPORT OBSERVER ===\n{obs_description}\n\n"
                f"Valuta se il task è completato.\n"
                f"Rispondi SOLO JSON: {{\"success\": true/false, \"reason\": \"...\", \"suggestions\": \"\"}}"
            )
            m40_result = self.m40.generate(
                [{"role": "system", "content": _M40_VISUAL_JUDGE_SYSTEM},
                 {"role": "user",   "content": prompt}],
                max_tokens=200, label="M40→ObserverJudge"
            )
            parsed = _safe_json(m40_result["response"], {"success": False, "reason": obs.get("reason",""), "suggestions": ""})
            success_raw = parsed.get("success", False)
            m40_success = success_raw.lower() in ("true","1","yes","sì") if isinstance(success_raw, str) else bool(success_raw)
            return {
                "success": m40_success,
                "reason": parsed.get("reason", ""),
                "suggestions": parsed.get("suggestions", ""),
                "thinking": f"Observer: {obs.get('description','')[:150]}",
                "pipeline": "observer+m40",
            }

        # --- Step 4: fallback pixel analysis + MI50 vision ---
        if not frame_paths:
            return {"success": False, "reason": "Nessun frame e observer fallito.", "suggestions": "", "thinking": "", "pipeline": "no-data"}

        print("\n  [Evaluator] Fallback pixel analysis + MI50-vision...", flush=True)
        pixel_description = _build_pixel_description(frame_paths)
        animation_detected = _frames_differ(frame_paths)
        serial_info = f"\nSerial: {serial_output[:300]}" if serial_output and serial_output.strip() else ""

        prompt = (
            f"Task: {task}\n\n"
            f"Analisi pixel OLED:\n{pixel_description}\n"
            f"Animazione: {'SÌ' if animation_detected else 'NO'}{serial_info}\n\n"
            f"Rispondi SOLO JSON: {{\"success\": true/false, \"reason\": \"...\", \"suggestions\": \"\"}}"
        )
        m40_result = self.m40.generate(
            [{"role": "system", "content": _M40_VISUAL_JUDGE_SYSTEM},
             {"role": "user",   "content": prompt}],
            max_tokens=300, label="M40→VisualJudge"
        )
        parsed = _safe_json(m40_result["response"], {"success": False, "reason": m40_result["response"], "suggestions": ""})
        success_raw = parsed.get("success", False)
        m40_success = success_raw.lower() in ("true","1","yes","sì") if isinstance(success_raw, str) else bool(success_raw)

        if m40_success:
            return {"success": True, "reason": parsed.get("reason",""), "suggestions": "", "thinking": pixel_description[:200], "pipeline": "pixel+m40"}

        print("\n  [Evaluator] M40 incerto → fallback MI50-vision", flush=True)
        return self._mi50_visual_fallback(task, frame_paths, serial_output, parsed.get("reason",""))

    def _mi50_visual_fallback(
        self,
        task: str,
        frame_paths: list,
        serial_output: str,
        m40_reason: str,
    ) -> dict:
        """Fallback: invia a MI50-vision le 3 versioni preprocessate (crop+threshold+edge)."""
        cropped, threshold_paths, edge_paths, tmpfiles = _preprocess_multi(frame_paths)

        # Manda tutte le versioni: crop + threshold (le più utili)
        best_paths = cropped + threshold_paths
        if not best_paths:
            best_paths = frame_paths

        content = []
        for _ in best_paths:
            content.append({"type": "image"})

        prompt_parts = [
            f"Task richiesto: {task}",
            "",
            f"Nota: analisi pixel automatica ha rilevato: {m40_reason}",
            "Guarda le immagini (originali crop + versioni threshold B&W) e verifica.",
            "",
            "Il display OLED ha sfondo NERO — è normale. Cerca pixel BIANCHI LUMINOSI.",
            "Versioni threshold: tutto bianco = pixel OLED acceso, tutto nero = spento.",
            "",
            "REGOLA: success=false SOLO se non vedi nessun pixel bianco.",
        ]
        if serial_output:
            prompt_parts.append(f"\nSerial: {serial_output[:200]}")
        prompt_parts.append(
            '\nRispondi SOLO con JSON: {"success": true/false, "reason": "...", "suggestions": ""}'
        )

        content.append({"type": "text", "text": "\n".join(prompt_parts)})
        messages = [
            {"role": "system", "content": "Sei un giudice tecnico. Rispondi SOLO con JSON."},
            {"role": "user",   "content": content},
        ]

        result = self.mi50.generate_with_images(messages, best_paths, max_new_tokens=512)

        for tmp in tmpfiles:
            try:
                os.unlink(tmp)
            except Exception:
                pass

        parsed = _safe_json(result["response"], fallback={
            "success": False, "reason": result["response"], "suggestions": "",
        })
        success_raw = parsed.get("success", False)
        success = success_raw.lower() in ("true","1","yes","sì") if isinstance(success_raw, str) else bool(success_raw)
        return {
            "success": success,
            "reason": parsed.get("reason", ""),
            "suggestions": parsed.get("suggestions", ""),
            "thinking": result["thinking"],
            "pipeline": "mi50-vision-fallback",
        }

    def evaluate_visual(
        self,
        task: str,
        serial_output: str,
        frame_paths: list,
        code: str = "",
    ) -> dict:
        """
        Legacy: evaluate_visual con solo MI50-vision + preprocessing base.
        Mantenuto per compatibilità con tool_agent.py.
        Ora reindirizza alla pipeline opencv+m40 con fallback MI50.
        """
        return self.evaluate_visual_opencv(task, frame_paths, serial_output)
