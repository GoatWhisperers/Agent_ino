"""
Client M40 — Qwen3.5-9B-Q5_K_M via llama-server HTTP.
Nessun caricamento modello: il server è già attivo sulla porta 11435.
"""
import json
import re
import sys
import requests
import agent.dashboard as dashboard

M40_URL = "http://localhost:11435/v1/chat/completions"
M40_HEALTH_URL = "http://localhost:11435/health"


class M40Client:
    def __init__(self, timeout: int = 120):
        self.timeout = timeout

    def generate(
        self,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.1,
        label: str = "M40",
    ) -> dict:
        """
        Chiama llama-server M40 con l'API OpenAI-compatible, con streaming.

        messages: [{"role": "system"|"user"|"assistant", "content": str}]
        label   : etichetta mostrata in console durante la generazione
        ritorna: {"thinking": str, "response": str, "raw": str}
        """
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        raw = self._stream_and_print(payload, label)
        thinking, response = self._extract_thinking(raw)
        return {"thinking": thinking, "response": response, "raw": raw}

    def _stream_and_print(self, payload: dict, label: str) -> str:
        """Esegue la richiesta in streaming, stampa i token in console, ritorna il testo completo."""
        print(f"\n  [{label}] ", end="", flush=True)
        raw = ""
        in_think = False

        with requests.post(M40_URL, json=payload, stream=True, timeout=self.timeout) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    token = chunk["choices"][0].get("delta", {}).get("content", "")
                except Exception:
                    continue
                if not token:
                    continue

                raw += token

                # Cambia stile in base a thinking vs risposta
                if "<think>" in token:
                    in_think = True
                    print("\n  💭 ", end="", flush=True)
                    token = token.replace("<think>", "")
                if "</think>" in token:
                    in_think = False
                    print("\n  →  ", end="", flush=True)
                    token = token.replace("</think>", "")

                # Dashboard: thinking con sorgente separata per stile diverso
                dashboard.token("m40-think" if in_think else "m40", token)
                print(token, end="", flush=True)

        print()  # newline finale
        return raw

    def is_available(self) -> bool:
        """Controlla che llama-server risponda su /health."""
        try:
            r = requests.get(M40_HEALTH_URL, timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------
    # Utility interna
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_thinking(raw: str) -> tuple[str, str]:
        """
        Estrae (thinking, response) dal raw output.
        Se non ci sono tag <think>, thinking è stringa vuota.
        """
        m = re.search(r"<think>(.*?)</think>", raw, re.DOTALL)
        thinking = m.group(1).strip() if m else ""
        response = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        return thinking, response
