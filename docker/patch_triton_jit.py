"""
Patch triton/runtime/jit.py per correggere il crash con @triton.jit
su funzioni con decoratori multipli in Python 3.11.

Problema: in Python 3.11, co_firstlineno punta al primo decorator.
inspect.getsource() restituisce il sorgente dal primo decorator, ma
pytorch-triton-rocm 3.2.0 ha un bug per cui non include la riga 'def'
nel blocco restituito. Il regex "^def\s+\w+\s*\(" restituisce None.

Fix: se il regex fallisce, prova con indentazione opzionale (^\s*def...).
"""
import re

JIT_FILE = '/usr/local/lib/python3.11/dist-packages/triton/runtime/jit.py'

OLD = '        self.src = self.src[re.search(r"^def\\s+\\w+\\s*\\(", self.src, re.MULTILINE).start():]'

NEW = (
    '        _m = re.search(r"^def\\s+\\w+\\s*\\(", self.src, re.MULTILINE)\n'
    '        if _m is None:\n'
    '            _m = re.search(r"^\\s*def\\s+\\w+\\s*\\(", self.src, re.MULTILINE)\n'
    '        if _m is not None:\n'
    '            self.src = self.src[_m.start():]'
)

src = open(JIT_FILE).read()
assert OLD in src, f"Riga target non trovata in {JIT_FILE} — il patch potrebbe essere già applicato o la versione è diversa"
patched = src.replace(OLD, NEW, 1)
open(JIT_FILE, 'w').write(patched)
print(f"Patch applicata a {JIT_FILE} — OK")
