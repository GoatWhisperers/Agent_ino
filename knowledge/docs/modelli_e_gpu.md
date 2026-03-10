# Modelli e GPU — Configurazione

Come sono usate le due GPU nell'agente.

---

## MI50 — AMD, 32 GB VRAM (ROCm) — multimodale

**Ruolo**: cervello. Reasoning profondo, thinking attivo, tutte le decisioni.

**Modello**: Qwen3.5-9B multimodale (HuggingFace, bfloat16)
- Architettura: `Qwen3_5ForConditionalGeneration` — testo + visione
- Path: `/mnt/raid0/qwen3.5-9b`
- VRAM occupata: ~19 GB
- Velocità: 5-15 min per risposta con thinking lungo (normale)
- Vision encoder: patch 16×16, hidden_size 1152, merge spaziale 2×2

**Come viene usato**: server HTTP persistente `agent/mi50_server.py` sulla porta `11434`.
Il server carica il modello una volta e rimane in VRAM per tutta la sessione. `agent/mi50_client.py` è il client HTTP — stessa interfaccia pubblica di prima, zero modifiche agli altri moduli.

**Avvio**:
```bash
python agent/mi50_server.py &
curl http://localhost:11434/health   # {"status":"ok"}
```

**Variabili d'ambiente** (impostate automaticamente da `mi50_client.py` prima di importare torch):
```python
HSA_OVERRIDE_GFX_VERSION=9.0.6
HIP_VISIBLE_DEVICES=0
HSA_ENABLE_SDMA=0
PYTORCH_HIP_ALLOC_CONF=max_split_size_mb:128,garbage_collection_threshold:0.95,expandable_segments:True
HF_HOME=/mnt/raid0/hf_cache
```

**Pattern di caricamento**:
```python
model = AutoModelForCausalLM.from_pretrained(path, torch_dtype=torch.bfloat16)
model.to("cuda")
```
MAI usare `device_map="auto"` o `low_cpu_mem_usage=True` — su MI50/ROCm causano problemi.

**Thinking**: Qwen3.5 produce blocchi `<think>...</think>` prima della risposta. Il client li estrae separatamente — il thinking viene loggato nel JSONL e non viene mai scartato. È informazione utile.

**Usato in**: Analyst, Orchestrator, Error Analyzer, Evaluator (testo + visione), Learner.

**Modalità visione**: il metodo `generate_with_images(messages, image_paths)` in `mi50_client.py` usa `AutoProcessor` per integrare frame JPEG nel contesto. I frame vengono passati come `PIL.Image` e convertiti in patch dal processor. Usato dall'Evaluator per la valutazione visiva tramite webcam Raspberry Pi.

---

## M40 — NVIDIA Tesla, 11.5 GB VRAM (CUDA sm_52)

**Ruolo**: mani. Generazione veloce, iterazioni rapide di codice.

**Modello**: Qwen3.5-9B-Q5_K_M (GGUF quantizzato)
- Path: `/mnt/raid0/Qwen3.5-9B-Q5_K_M.gguf`
- VRAM occupata: ~6.5 GB
- Velocità: ~33 tok/s

**Come viene usato**: tramite `llama-server` HTTP sulla porta `11435`. Il client è `agent/m40_client.py` che fa richieste HTTP REST.

**Avvio del server**:
```bash
/mnt/raid0/llama-cpp-m40/start_cuda.sh
# oppure manualmente:
LD_LIBRARY_PATH=/mnt/raid0/llama-cpp-m40/build_cuda/bin:/usr/local/cuda-11.8/lib64:/usr/lib/x86_64-linux-gnu \
/mnt/raid0/llama-cpp-m40/build_cuda/bin/llama-server \
  -m /mnt/raid0/Qwen3.5-9B-Q5_K_M.gguf \
  --port 11435 --host 0.0.0.0 -ngl 99
```

**Verifica**:
```bash
curl http://localhost:11435/health   # {"status":"ok"}
```

**Nota**: PyTorch >= 2.1 non supporta sm_52 (architettura M40). Usare solo llama.cpp/llama-server per il M40 — MAI caricare modelli PyTorch su questa GPU.

**Usato in**: Generator (generazione codice), Patcher (correzione codice).

---

## Venv Python

```
programmatore_di_arduini/.venv/
```

Creato con `python3 -m venv .venv --system-site-packages` più un file `.pth` che aggiunge i site-packages di `project_jedi/.venv` al path. Questo rende disponibile PyTorch ROCm (19 GB, non duplicato) in sola lettura.

**Pacchetti aggiuntivi nel venv locale**:
- `transformers >= 5.3.0` (Qwen3.5 richiede questa versione)
- `chromadb`
- `sentence-transformers`
- `pyserial`
- `requests`

**NON toccare** `project_jedi/.venv` — è un progetto separato e isolato.
