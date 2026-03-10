"""
Test mock per Generator e le utility di estrazione.

Esegui con:
    /home/lele/codex-openai/programmatore_di_arduini/.venv/bin/python \
        -m pytest agent/test_generator.py -v
oppure direttamente:
    /home/lele/codex-openai/programmatore_di_arduini/.venv/bin/python \
        agent/test_generator.py
"""
import sys
import unittest

sys.path.insert(0, "/home/lele/codex-openai/programmatore_di_arduini")

# ---------------------------------------------------------------------------
# Mock client — nessun import di torch, nessun caricamento modello
# ---------------------------------------------------------------------------

class MockM40Client:
    """Simula M40Client senza richiedere llama-server."""

    def __init__(self, response_override: str = ""):
        self._resp = response_override

    def generate(self, messages, max_tokens=1024, temperature=0.1):
        return {
            "thinking": "",
            "response": self._resp,
            "raw": self._resp,
        }


# ---------------------------------------------------------------------------
# Import Generator patchando il modulo m40_client PRIMA dell'import
# ---------------------------------------------------------------------------

import types, importlib

def _make_generator_with_mock(mock_response: str):
    """Ritorna un'istanza di Generator con client mockato."""
    # Importa il modulo senza eseguire import reali di torch
    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "agent.generator",
        os.path.join(
            os.path.dirname(__file__),
            "generator.py",
        ),
    )
    mod = importlib.util.module_from_spec(spec)

    # Patch: inserisce un finto m40_client nel sys.modules
    fake_m40 = types.ModuleType("agent.m40_client")

    class _FakeM40Client:
        def __init__(self):
            pass
        def generate(self, messages, max_tokens=1024, temperature=0.1):
            return {"thinking": "", "response": mock_response, "raw": mock_response}

    fake_m40.M40Client = _FakeM40Client
    sys.modules["agent.m40_client"] = fake_m40

    spec.loader.exec_module(mod)
    gen = mod.Generator()
    return gen, mod


# ---------------------------------------------------------------------------
# Test _extract_thinking (standalone, copiata da m40_client)
# ---------------------------------------------------------------------------

import re

def _extract_thinking(raw: str):
    """Copia della funzione per testare in isolamento."""
    m = re.search(r"<think>(.*?)</think>", raw, re.DOTALL)
    thinking = m.group(1).strip() if m else ""
    response = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return thinking, response


class TestExtractThinking(unittest.TestCase):

    def test_con_think_tag(self):
        raw = "<think>Sto ragionando sul problema.</think>\nEcco il codice."
        t, r = _extract_thinking(raw)
        self.assertEqual(t, "Sto ragionando sul problema.")
        self.assertEqual(r, "Ecco il codice.")

    def test_senza_think_tag(self):
        raw = "Ecco il codice direttamente."
        t, r = _extract_thinking(raw)
        self.assertEqual(t, "")
        self.assertEqual(r, "Ecco il codice direttamente.")

    def test_think_multilinea(self):
        raw = "<think>\nLinea 1\nLinea 2\n</think>\nRisposta finale."
        t, r = _extract_thinking(raw)
        self.assertIn("Linea 1", t)
        self.assertIn("Linea 2", t)
        self.assertEqual(r, "Risposta finale.")

    def test_think_tag_vuoto(self):
        raw = "<think></think>Solo testo."
        t, r = _extract_thinking(raw)
        self.assertEqual(t, "")
        self.assertEqual(r, "Solo testo.")

    def test_think_con_codice_nella_risposta(self):
        raw = (
            "<think>Devo usare millis().</think>\n"
            "```cpp\nvoid setup(){}\nvoid loop(){}\n```"
        )
        t, r = _extract_thinking(raw)
        self.assertIn("millis()", t)
        self.assertIn("```cpp", r)

    def test_output_vuoto(self):
        t, r = _extract_thinking("")
        self.assertEqual(t, "")
        self.assertEqual(r, "")


# ---------------------------------------------------------------------------
# Test _extract_code
# ---------------------------------------------------------------------------

class TestExtractCode(unittest.TestCase):

    def setUp(self):
        self.gen, _ = _make_generator_with_mock("")

    def test_fence_cpp(self):
        text = "Ecco il codice:\n```cpp\nvoid setup(){}\nvoid loop(){}\n```\nFine."
        code = self.gen._extract_code(text)
        self.assertIn("void setup", code)
        self.assertNotIn("```", code)
        self.assertNotIn("Ecco il codice", code)

    def test_fence_arduino(self):
        text = "```arduino\n#include <Arduino.h>\nvoid setup(){}\n```"
        code = self.gen._extract_code(text)
        self.assertIn("#include", code)
        self.assertNotIn("```", code)

    def test_fence_generica(self):
        text = "Risposta:\n```\nvoid setup(){}\nvoid loop(){}\n```"
        code = self.gen._extract_code(text)
        self.assertIn("void setup", code)

    def test_fence_c_plusplus(self):
        text = "```c++\nint x = 0;\n```"
        code = self.gen._extract_code(text)
        self.assertEqual(code, "int x = 0;")

    def test_nessuna_fence_fallback(self):
        text = "void setup(){}\nvoid loop(){}"
        code = self.gen._extract_code(text)
        self.assertIn("void setup", code)

    def test_rimuove_think_prima_del_codice(self):
        text = "<think>Penso...</think>\n```cpp\nvoid setup(){}\n```"
        code = self.gen._extract_code(text)
        self.assertIn("void setup", code)
        self.assertNotIn("<think>", code)

    def test_testo_prima_e_dopo_fence(self):
        text = (
            "Ecco lo sketch:\n"
            "```cpp\n"
            "#include <Wire.h>\nvoid setup(){Wire.begin();}\nvoid loop(){}\n"
            "```\n"
            "Spero sia utile."
        )
        code = self.gen._extract_code(text)
        self.assertIn("#include <Wire.h>", code)
        self.assertNotIn("Ecco lo sketch", code)
        self.assertNotIn("Spero sia utile", code)

    def test_fence_con_spazio_dopo_backtick(self):
        # Alcune fence hanno uno spazio prima del newline
        text = "```cpp \nvoid setup(){}\nvoid loop(){}\n```"
        code = self.gen._extract_code(text)
        # Fallback: il regex usa \s* dopo il linguaggio, deve funzionare
        self.assertIn("void", code)

    def test_output_vuoto(self):
        code = self.gen._extract_code("")
        self.assertEqual(code, "")


# ---------------------------------------------------------------------------
# Test generate_code (mock end-to-end)
# ---------------------------------------------------------------------------

class TestGenerateCode(unittest.TestCase):

    def test_ritorna_codice_da_fence(self):
        mock_resp = "```cpp\nvoid setup(){}\nvoid loop(){}\n```"
        gen, _ = _make_generator_with_mock(mock_resp)
        result = gen.generate_code("Fai lampeggiare LED")
        self.assertIn("void setup", result["code"])
        self.assertNotIn("```", result["code"])
        self.assertIn("thinking", result)
        self.assertIn("raw", result)

    def test_ritorna_keys_corrette(self):
        mock_resp = "```cpp\nvoid setup(){}\nvoid loop(){}\n```"
        gen, _ = _make_generator_with_mock(mock_resp)
        result = gen.generate_code("Test")
        self.assertIn("code", result)
        self.assertIn("thinking", result)
        self.assertIn("raw", result)

    def test_codice_senza_fence(self):
        mock_resp = "void setup(){}\nvoid loop(){}"
        gen, _ = _make_generator_with_mock(mock_resp)
        result = gen.generate_code("Test senza fence")
        self.assertIn("void setup", result["code"])


# ---------------------------------------------------------------------------
# Test patch_code (mock end-to-end)
# ---------------------------------------------------------------------------

class TestPatchCode(unittest.TestCase):

    def test_patch_corregge_codice(self):
        original = "void setup(){} void loop(){ digitalRead(13) }"
        errors = [{"line": 1, "type": "error", "message": "missing semicolon"}]
        fixed_code = "void setup(){}\nvoid loop(){\n  digitalRead(13);\n}"
        mock_resp = f"```cpp\n{fixed_code}\n```"
        gen, _ = _make_generator_with_mock(mock_resp)

        result = gen.patch_code(original, errors)
        self.assertIn("void setup", result["code"])
        self.assertIn("thinking", result)
        self.assertIn("raw", result)

    def test_patch_con_analisi(self):
        code = "void setup(){}"
        errors = [{"line": 1, "type": "warning", "message": "unused variable"}]
        mock_resp = "```cpp\nvoid setup(){}\nvoid loop(){}\n```"
        gen, _ = _make_generator_with_mock(mock_resp)

        result = gen.patch_code(code, errors, analysis="Manca void loop()")
        self.assertIn("void", result["code"])


# ---------------------------------------------------------------------------
# Esecuzione diretta
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
