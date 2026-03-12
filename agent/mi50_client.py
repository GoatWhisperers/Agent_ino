"""
Client MI50 — chiama mi50_server.py via HTTP, con streaming dei token.

Il server deve essere già avviato prima di usare questo client:
    python agent/mi50_server.py &
    curl http://localhost:11434/health   # deve rispondere {"status":"ok"}

L'interfaccia pubblica è identica a prima:
    client = MI50Client.get()
    result = client.generate(messages, label="Orchestrator")
    result = client.generate_with_images(messages, image_paths)
"""

import json
import re
import threading
import time
import requests

MI50_SERVER_URL = "http://localhost:11434"
_DASH_URL = "http://localhost:7700/emit"


class _TokenBatcher:
    """Accumula token e li manda alla dashboard via HTTP ogni 200ms."""

    def __init__(self):
        self._buf = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def push(self, source: str, text: str):
        with self._lock:
            self._buf.append((source, text))

    def flush(self):
        self._send()

    def _send(self):
        with self._lock:
            if not self._buf:
                return
            # Raggruppa per source consecutiva
            batches: list[tuple[str, str]] = []
            for src, txt in self._buf:
                if batches and batches[-1][0] == src:
                    batches[-1] = (src, batches[-1][1] + txt)
                else:
                    batches.append((src, txt))
            self._buf.clear()
        for src, txt in batches:
            try:
                requests.post(_DASH_URL, json={"type": "token", "source": src, "text": txt},
                              timeout=1)
            except Exception:
                pass

    def _loop(self):
        while not self._stop.wait(0.2):
            self._send()


_batcher = _TokenBatcher()
_DEFAULT_TIMEOUT = 1200  # 20 min — le risposte di MI50 possono essere lunghe


class MI50Client:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "MI50Client":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._check_server()

    def _check_server(self):
        try:
            r = requests.get(f"{MI50_SERVER_URL}/health", timeout=10)
            r.raise_for_status()
            print(f"[MI50Client] Server MI50 raggiungibile: {r.json()}")
        except Exception as e:
            raise RuntimeError(
                f"[MI50Client] Server MI50 non raggiungibile su {MI50_SERVER_URL}.\n"
                f"Avvialo con: python agent/mi50_server.py\n"
                f"Errore: {e}"
            )

    def generate(
        self,
        messages: list[dict],
        max_new_tokens: int = 1024,
        label: str = "MI50",
    ) -> dict:
        """
        messages: [{"role": "system"|"user"|"assistant", "content": str}]
        label   : etichetta mostrata in console durante la generazione
        ritorna: {"thinking": str, "response": str, "raw": str}
        """
        print(f"\n  [{label}] ", end="", flush=True)
        raw = ""
        in_think = False

        # Rileva /no_think nel primo system prompt
        thinking = not any(
            m.get("role") == "system" and m.get("content", "").startswith("/no_think")
            for m in messages
        )
        with requests.post(
            f"{MI50_SERVER_URL}/generate_stream",
            json={"messages": messages, "max_new_tokens": max_new_tokens, "thinking": thinking},
            stream=True,
            timeout=_DEFAULT_TIMEOUT,
        ) as resp:
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
                    token = json.loads(data_str).get("token", "")
                except Exception:
                    continue
                if not token:
                    continue

                raw += token
                _batcher.push("mi50", token)

                if "<think>" in token:
                    in_think = True
                    print("\n  💭 ", end="", flush=True)
                    token = token.replace("<think>", "")
                if "</think>" in token:
                    in_think = False
                    print("\n  →  ", end="", flush=True)
                    token = token.replace("</think>", "")

                print(token, end="", flush=True)

        print()  # newline finale
        _batcher.flush()
        thinking, response = self._extract_thinking(raw)
        return {"thinking": thinking, "response": response, "raw": raw}

    def generate_with_images(
        self,
        messages: list[dict],
        image_paths: list[str],
        max_new_tokens: int = 1024,
        label: str = "MI50-vision",
    ) -> dict:
        """
        Chiamata non-streaming (visione è più rara, non vale la complessità SSE).
        ritorna: {"thinking": str, "response": str, "raw": str}
        """
        print(f"\n  [{label}] elaborazione immagini... ", end="", flush=True)
        r = requests.post(
            f"{MI50_SERVER_URL}/generate_with_images",
            json={
                "messages": messages,
                "image_paths": image_paths,
                "max_new_tokens": max_new_tokens,
            },
            timeout=_DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        print("fatto.")
        return r.json()

    def unload(self) -> None:
        """No-op: il server gestisce la propria VRAM."""
        print("[MI50Client] unload() ignorato — il server è persistente.")

    @staticmethod
    def _extract_thinking(raw: str) -> tuple[str, str]:
        m = re.search(r"<think>(.*?)</think>", raw, re.DOTALL)
        thinking = m.group(1).strip() if m else ""
        response = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        return thinking, response
