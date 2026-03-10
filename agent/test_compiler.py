"""Test suite for agent/compiler.py — tests both a valid and an invalid sketch."""

import os
import sys
import tempfile

sys.path.insert(0, "/home/lele/codex-openai/programmatore_di_arduini")

from agent.compiler import compile_sketch

# ---------------------------------------------------------------------------
# Sketch sorgenti
# ---------------------------------------------------------------------------

VALID_SKETCH = """
void setup() { pinMode(13, OUTPUT); }
void loop() { digitalWrite(13, HIGH); delay(500); digitalWrite(13, LOW); delay(500); }
"""

INVALID_SKETCH = """
void setup() { undeclared_function(); }
void loop() {}
"""


def run_tests() -> None:
    with tempfile.TemporaryDirectory() as tmp:

        # ------------------------------------------------------------------
        # Test 1: sketch valido
        # ------------------------------------------------------------------
        sketch_dir = os.path.join(tmp, "blink")
        os.makedirs(sketch_dir)
        with open(os.path.join(sketch_dir, "blink.ino"), "w") as f:
            f.write(VALID_SKETCH)

        r = compile_sketch(sketch_dir)
        print(f"[VALIDO]   success={r['success']}, errors={r['errors']}, binary={r['binary_path']}")
        assert r["success"], (
            f"Lo sketch valido dovrebbe compilare senza errori.\n"
            f"stderr:\n{r['raw_stderr']}\nstdout:\n{r['raw_stdout']}"
        )
        assert not r["errors"], f"Non dovrebbero esserci errori: {r['errors']}"

        # ------------------------------------------------------------------
        # Test 2: sketch invalido
        # ------------------------------------------------------------------
        sketch_dir2 = os.path.join(tmp, "broken")
        os.makedirs(sketch_dir2)
        with open(os.path.join(sketch_dir2, "broken.ino"), "w") as f:
            f.write(INVALID_SKETCH)

        r2 = compile_sketch(sketch_dir2)
        print(f"[INVALIDO] success={r2['success']}, errori={len(r2['errors'])}")
        for e in r2["errors"]:
            print(f"  [{e['type']}] {e['file']}:{e['line']}:{e['col']} — {e['message']}")

        assert not r2["success"], "Lo sketch invalido NON dovrebbe compilare con successo."
        assert len(r2["errors"]) > 0, (
            f"Dovrebbero esserci errori strutturati.\n"
            f"stderr:\n{r2['raw_stderr']}\nstdout:\n{r2['raw_stdout']}"
        )

        print("\nTutti i test superati.")


if __name__ == "__main__":
    run_tests()
