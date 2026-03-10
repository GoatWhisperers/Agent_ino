"""
Evaluator — usa MI50 per valutare se il task è stato completato.
"""
import json
import re
import sys

sys.path.insert(0, "/home/lele/codex-openai/programmatore_di_arduini")

from agent.mi50_client import MI50Client  # noqa: E402

_EVAL_SYSTEM = """/no_think
Sei un giudice tecnico per progetti Arduino.
Il tuo output deve essere ESCLUSIVAMENTE un oggetto JSON valido. Nessun testo prima o dopo.

STRUTTURA OBBLIGATORIA:
{"success":true,"reason":"...","suggestions":""}

- success: true se il task è completato, false altrimenti
- reason: stringa, spiegazione concisa della valutazione
- suggestions: stringa, cosa cambiare se success=false, stringa vuota se success=true

Rispondi SOLO con il JSON. Zero testo aggiuntivo.
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


class Evaluator:
    def __init__(self):
        self.client = MI50Client.get()

    def evaluate(self, task: str, serial_output: str, code: str = "") -> dict:
        """
        Valuta se l'output seriale corrisponde al task.

        ritorna: {
            "success": bool,
            "reason": str,
            "suggestions": str,
            "thinking": str
        }
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
            {"role": "user", "content": "\n".join(user_parts)},
        ]

        result = self.client.generate(messages, max_new_tokens=512, label="MI50→Evaluator")
        parsed = _safe_json(
            result["response"],
            fallback={
                "success": False,
                "reason": result["response"],
                "suggestions": "",
            },
        )

        # Normalizza il campo success in bool
        success_raw = parsed.get("success", False)
        if isinstance(success_raw, str):
            success = success_raw.lower() in ("true", "1", "yes", "sì")
        else:
            success = bool(success_raw)

        return {
            "success": success,
            "reason": parsed.get("reason", ""),
            "suggestions": parsed.get("suggestions", ""),
            "thinking": result["thinking"],
        }

    def evaluate_visual(
        self,
        task: str,
        frame_paths: list,
        serial_output: str,
        code: str = "",
    ) -> dict:
        """
        Valuta visivamente il risultato usando frame catturati dall'ESP32.

        frame_paths : path locali delle immagini (sul server)
        serial_output: output seriale già filtrato (senza segnali VCAP)
        ritorna: {"success": bool, "reason": str, "suggestions": str, "thinking": str}
        """
        # Costruisci content con placeholder immagini seguiti dal testo
        content = []
        for _ in frame_paths:
            content.append({"type": "image"})

        serial_snippet = serial_output[:500] if serial_output else "(nessun output seriale)"

        prompt_parts = [
            "Sei un esperto di sistemi embedded.",
            f"Analizza questi {len(frame_paths)} frame catturati dall'ESP32 durante "
            "l'esecuzione del programma.",
            f"Task originale: {task}",
            f"Output seriale: {serial_snippet}",
        ]
        if code:
            prompt_parts.append(f"Codice caricato (estratto):\n{code[:600]}")

        prompt_parts.append(
            "Il programma ha funzionato correttamente? "
            'Rispondi SOLO con JSON: {"success": bool, "reason": str, "suggestions": str}'
        )

        content.append({"type": "text", "text": "\n".join(prompt_parts)})

        messages = [
            {
                "role": "user",
                "content": content,
            }
        ]

        result = self.client.generate_with_images(messages, frame_paths, max_new_tokens=512)
        parsed = _safe_json(
            result["response"],
            fallback={
                "success": False,
                "reason": result["response"],
                "suggestions": "",
            },
        )

        success_raw = parsed.get("success", False)
        if isinstance(success_raw, str):
            success = success_raw.lower() in ("true", "1", "yes", "sì")
        else:
            success = bool(success_raw)

        return {
            "success": success,
            "reason": parsed.get("reason", ""),
            "suggestions": parsed.get("suggestions", ""),
            "thinking": result["thinking"],
        }
