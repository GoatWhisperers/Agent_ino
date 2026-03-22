"""
Learner — usa MI50 per estrarre pattern da run riuscite e aggiornare il DB.
"""
import json
import re
import sys

sys.path.insert(0, "/home/lele/codex-openai/programmatore_di_arduini")

from agent.mi50_client import MI50Client  # noqa: E402
from knowledge.db import add_lesson, init_db

_LEARN_SYSTEM = """
Sei un esperto Arduino che analizza run riuscite per estrarre conoscenza riutilizzabile.
Il tuo output deve essere ESCLUSIVAMENTE un oggetto JSON valido. Nessun testo prima o dopo.

STRUTTURA OBBLIGATORIA:
{
  "snippet": {"description": "...", "tags": []},
  "libraries": [{"name": "...", "reason": "..."}],
  "error_fixes": [{"pattern": "...", "fix": "..."}],
  "lessons": [
    {
      "task_type": "categoria breve es. 'OLED animation'",
      "lesson": "cosa bisogna sempre fare/specificare per questo tipo di task",
      "spec_hint": "testo esatto da mettere nella task description la prossima volta",
      "hardware_quirk": "nota hardware specifica, oppure null"
    }
  ]
}

- snippet.description: stringa, descrizione breve del pattern
- snippet.tags: array di stringhe, categorie (es. "oled", "animation", "esp32")
- libraries: librerie usate e perché (vuoto se nessuna)
- error_fixes: errori incontrati e fix applicati (vuoto se nessuno)
- lessons: lezioni apprese — cosa NON è ovvio e che serve specificare esplicitamente
  la prossima volta per non perdere tentativi. Focus su:
  - dettagli della task description che erano cruciali per far funzionare il codice
  - comportamenti di M40 che richiedono correzione preventiva
  - quirk hardware specifici (pin, indirizzi I2C, costruttori, ecc.)
  Includi almeno 1 lesson anche se la run è andata liscia al primo tentativo.

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



class Learner:
    def __init__(self):
        self.client = MI50Client.get()

    def extract_patterns(
        self,
        task: str,
        code: str,
        iterations: list[dict],
    ) -> dict:
        """
        Dal codice funzionante e dalle iterazioni precedenti, estrae:
        - librerie usate e perché
        - pattern riutilizzabili
        - mappature errore→fix verificate

        iterations: lista di dict con almeno "errors" e "fix" (possono variare)

        ritorna: {
            "snippet": {"description": str, "tags": list},
            "libraries": [{"name": str, "reason": str}],
            "error_fixes": [{"pattern": str, "fix": str}],
            "thinking": str
        }
        """
        # Sintetizza le iterazioni in testo leggibile
        iter_parts = []
        for i, it in enumerate(iterations, 1):
            errors = it.get("errors", [])
            fix = it.get("fix", "")
            err_str = "; ".join(
                e.get("message", str(e)) for e in errors
            ) if isinstance(errors, list) else str(errors)
            iter_parts.append(f"Iterazione {i}: errori=[{err_str}], fix={fix}")
        iterations_text = "\n".join(iter_parts) if iter_parts else "(run riuscita al primo tentativo)"

        user_content = (
            f"Task: {task}\n\n"
            f"=== CODICE FINALE FUNZIONANTE ===\n{code}\n\n"
            f"=== ITERAZIONI PRECEDENTI ===\n{iterations_text}"
        )

        messages = [
            {"role": "system", "content": _LEARN_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        result = self.client.generate(messages, max_new_tokens=8192, label="MI50→Learner")
        parsed = _safe_json(
            result["response"],
            fallback={
                "snippet": {"description": task, "tags": []},
                "libraries": [],
                "error_fixes": [],
            },
        )

        # Salva le lessons nel DB e in ChromaDB
        lessons = parsed.get("lessons", [])
        saved_lessons = []
        if lessons:
            init_db()
            for les in lessons:
                if not les.get("lesson"):
                    continue
                try:
                    # add_lesson ora chiama index_lesson automaticamente (db.py KB auto-sync)
                    # Non chiamare index_lesson separatamente per evitare duplicazione in ChromaDB
                    lid = add_lesson(
                        task_type=les.get("task_type", "general"),
                        lesson=les.get("lesson", ""),
                        spec_hint=les.get("spec_hint") or "",
                        hardware_quirk=les.get("hardware_quirk") or "",
                        board="",  # universale — non leghiamo al board specifico
                    )
                    saved_lessons.append(lid)
                except Exception:
                    pass

        return {
            "snippet": parsed.get("snippet", {"description": task, "tags": []}),
            "libraries": parsed.get("libraries", []),
            "error_fixes": parsed.get("error_fixes", []),
            "lessons": lessons,
            "lessons_saved": len(saved_lessons),
            "thinking": result["thinking"],
        }
