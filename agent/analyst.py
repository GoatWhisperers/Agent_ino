"""
Analyst — usa MI50 per analizzare codice esistente.
Usato in 3 contesti:
1. Prima di generare: analizza codice simile trovato nel DB
2. CONTINUE: capisce stato di un progetto parziale
3. MODIFY: capisce cosa cambiare in un progetto funzionante
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, "/home/lele/codex-openai/programmatore_di_arduini")

from agent.mi50_client import MI50Client  # noqa: E402

_SIMILAR_SYSTEM = """
Sei un esperto Arduino. Analizza gli snippet di codice simili al task e
produci un riassunto di cosa è utile riutilizzare e cosa va adattato.
Sii conciso e pratico. Risposta in italiano, testo libero (non JSON).
"""

_PROJECT_STATE_SYSTEM = """
Sei un esperto Arduino. Analizza il codice fornito e produci una
valutazione dello stato del progetto.
Rispondi SEMPRE in JSON con questa struttura esatta:
{
  "status": "partial" | "broken" | "working",
  "summary": "<cosa fa il codice>",
  "missing": "<cosa manca per completarlo>"
}
Non aggiungere testo fuori dal JSON.
"""

_MODIFY_SYSTEM = """
Sei un esperto Arduino. Dato un codice funzionante e una richiesta di modifica,
analizza cosa va cambiato e cosa va mantenuto.
Rispondi SEMPRE in JSON con questa struttura esatta:
{
  "what_to_change": "<cosa modificare>",
  "what_to_keep": "<cosa mantenere invariato>",
  "approach": "<come effettuare la modifica>"
}
Non aggiungere testo fuori dal JSON.
"""


def _safe_json(text: str, fallback: dict) -> dict:
    m = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    else:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return fallback


class Analyst:
    def __init__(self):
        self.client = MI50Client.get()

    # ------------------------------------------------------------------
    # API pubblica
    # ------------------------------------------------------------------

    def analyze_similar_code(self, task: str, similar_codes: list[dict]) -> str:
        """
        Analizza codice simile trovato nel DB.
        Ritorna una stringa di contesto: cosa è utile, cosa va adattato.

        similar_codes: lista di dict con almeno "code" e opzionalmente "description"
        """
        # Limite per snippet: 800 char di codice — passa il codice intero se sta,
        # altrimenti taglia alla fine dell'ultima riga completa entro il limite.
        # Mai troncare in mezzo a una riga.
        MAX_CODE_CHARS = 800
        snippets_text_parts = []
        for i, item in enumerate(similar_codes, 1):
            desc = item.get("description", f"Snippet {i}")
            code = item.get("code", "")
            if len(code) > MAX_CODE_CHARS:
                # Taglia all'ultima riga completa entro il limite
                truncated = code[:MAX_CODE_CHARS].rsplit("\n", 1)[0]
                code = truncated + f"\n// ... (snippet troncato a {MAX_CODE_CHARS} char)"
            snippets_text_parts.append(f"--- Snippet {i}: {desc} ---\n{code}")
        snippets_text = "\n\n".join(snippets_text_parts)

        messages = [
            {"role": "system", "content": _SIMILAR_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Task da implementare: {task}\n\n"
                    f"Codice simile trovato nel DB:\n{snippets_text}"
                ),
            },
        ]

        result = self.client.generate(messages, max_new_tokens=1024, label="MI50→Analyst")
        return result["response"]

    def analyze_project_state(self, project_dir: str) -> dict:
        """
        Legge tutti i file .ino in project_dir + eventuali log (.jsonl).
        Ritorna: {
            "code": str,
            "status": str,   # "partial" | "broken" | "working"
            "summary": str,
            "missing": str,
            "thinking": str
        }
        """
        # Leggi tutti i .ino
        ino_files = sorted(glob.glob(os.path.join(project_dir, "*.ino")))
        code_parts = []
        for path in ino_files:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                code_parts.append(f"// === {os.path.basename(path)} ===\n" + f.read())
        code = "\n\n".join(code_parts)

        # Leggi log JSONL (ultimi 20 eventi per brevità)
        log_summary_parts = []
        jsonl_files = sorted(glob.glob(os.path.join(project_dir, "*.jsonl")))
        for log_path in jsonl_files:
            lines = []
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        lines.append(line)
            recent = lines[-20:]
            log_summary_parts.append(
                f"// Log: {os.path.basename(log_path)}\n" + "\n".join(recent)
            )
        logs_text = "\n\n".join(log_summary_parts)

        user_content_parts = ["Analizza il seguente codice Arduino:"]
        if code:
            user_content_parts.append(f"\n{code}")
        else:
            user_content_parts.append("\n(nessun file .ino trovato)")
        if logs_text:
            user_content_parts.append(f"\n\nLog recenti:\n{logs_text}")

        messages = [
            {"role": "system", "content": _PROJECT_STATE_SYSTEM},
            {"role": "user", "content": "\n".join(user_content_parts)},
        ]

        result = self.client.generate(messages, max_new_tokens=1024, label="MI50→Analyst")
        parsed = _safe_json(
            result["response"],
            fallback={
                "status": "partial",
                "summary": result["response"],
                "missing": "",
            },
        )
        return {
            "code": code,
            "status": parsed.get("status", "partial"),
            "summary": parsed.get("summary", ""),
            "missing": parsed.get("missing", ""),
            "thinking": result["thinking"],
        }

    def analyze_for_modify(self, code: str, modification_request: str) -> dict:
        """
        Dato codice funzionante e una richiesta di modifica.
        Ritorna: {
            "what_to_change": str,
            "what_to_keep": str,
            "approach": str,
            "thinking": str
        }
        """
        messages = [
            {"role": "system", "content": _MODIFY_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Richiesta di modifica: {modification_request}\n\n"
                    f"=== CODICE ATTUALE ===\n{code}"
                ),
            },
        ]

        result = self.client.generate(messages, max_new_tokens=1024, label="MI50→Analyst")
        parsed = _safe_json(
            result["response"],
            fallback={
                "what_to_change": result["response"],
                "what_to_keep": "",
                "approach": "",
            },
        )
        return {
            "what_to_change": parsed.get("what_to_change", ""),
            "what_to_keep": parsed.get("what_to_keep", ""),
            "approach": parsed.get("approach", ""),
            "thinking": result["thinking"],
        }
