"""
Patch transformers/models/qwen3_5/modeling_qwen3_5.py per MI50 (gfx906).

PROBLEMA:
  - Nel prefill path, il modello usa chunk_gated_delta_rule (fla).
  - chunk_gated_delta_rule chiama chunk_local_cumsum_vector_kernel (Triton).
  - Su MI50 (gfx906 con HSA_OVERRIDE=9.0.8) questo kernel crasha con SIGSEGV.

SOLUZIONE:
  - Fare in modo che self.chunk_gated_delta_rule usi fused_recurrent_gated_delta_rule.
  - fused_recurrent_gated_delta_rule usa kernel Triton diversi che funzionano su MI50.
  - Lievemente meno efficiente (O(T*D²) invece di O(T*D²/chunk)), ma stabile.
"""

MODELING_FILE = '/usr/local/lib/python3.11/dist-packages/transformers/models/qwen3_5/modeling_qwen3_5.py'

OLD = '        self.chunk_gated_delta_rule = chunk_gated_delta_rule or torch_chunk_gated_delta_rule'
NEW = '        self.chunk_gated_delta_rule = fused_recurrent_gated_delta_rule or torch_recurrent_gated_delta_rule  # MI50: use recurrent (chunk crashes on gfx906)'

src = open(MODELING_FILE).read()
assert OLD in src, f"Riga target non trovata in {MODELING_FILE}"
patched = src.replace(OLD, NEW, 1)
open(MODELING_FILE, 'w').write(patched)
print(f"Patch qwen3_5 applicata — chunk_gated_delta_rule → fused_recurrent su MI50 OK")
