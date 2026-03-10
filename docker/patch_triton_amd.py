"""
Patch triton/backends/amd/compiler.py per far girare kernel Triton su gfx906 (MI50).

PROBLEMA:
  - pytorch-triton-rocm 3.1.0 non supporta gfx906 come target di compilazione
    (PassManager::run failed: unsupported target 'gfx906')
  - gfx908 (MI100) è supportato, ma genera istruzioni MFMA non presenti su gfx906
  - Il crash (SIGSEGV exit 139) avviene quando MFMA viene eseguito su gfx906

SOLUZIONE:
  1. HSA_OVERRIDE_GFX_VERSION=9.0.8 → Triton vede gfx908 → compilazione riesce
  2. Patch compiler.py → forza matrix_instr_nonkdim=0 → niente MFMA → solo vector ops
  3. Vector ops di gfx908 sono ISA-compatibili con gfx906 → esecuzione OK

VERIFICA: minimal kernel (load/mul/store) compilato per gfx908 gira correttamente
su gfx906. Solo MFMA causa il crash.
"""

COMPILER_FILE = '/usr/local/lib/python3.11/dist-packages/triton/backends/amd/compiler.py'

# Patch: forza matrix_instr_nonkdim=0 in add_accelerate_matmul
OLD = 'amd.passes.ttgpuir.add_accelerate_matmul(pm, options.arch, options.matrix_instr_nonkdim, options.kpack)'
NEW = 'amd.passes.ttgpuir.add_accelerate_matmul(pm, options.arch, 0, options.kpack)  # MI50: force nonkdim=0 → no MFMA'

src = open(COMPILER_FILE).read()
assert OLD in src, f"Riga target non trovata in {COMPILER_FILE}"
patched = src.replace(OLD, NEW, 1)
open(COMPILER_FILE, 'w').write(patched)
print(f"Patch AMD compiler applicata a {COMPILER_FILE} — OK (MFMA disabilitato)")
