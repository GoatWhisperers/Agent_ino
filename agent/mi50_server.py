"""
MI50 Server — Qwen3.5-9B persistente su ROCm.

Carica il modello una volta sola e rimane in VRAM per tutta la sessione.
Espone un'API HTTP identica all'interfaccia di m40_client.py.

Avvio:
    (dentro Docker — gestito da run_mi50.sh / start_servers.sh)

Verifica:
    curl http://localhost:11434/health

Limiti di contesto:
    MAX_INPUT_TOKENS = 6144  — input troncato a questo valore (OOM prevention)
    max_new_tokens default = 1024
    Con attn_implementation='eager' (no Triton/flash-attn):
      - Prefill peak VRAM a 6144 tok: ~18GB modello + ~3GB attn = ~21GB su 32GB ✓
      - Nessun SIGSEGV da kernel Triton su gfx906
"""

import argparse
import json
import os
import sys
import threading

# env vars PRIMA di torch
os.environ["HSA_OVERRIDE_GFX_VERSION"] = "9.0.6"
os.environ["HIP_VISIBLE_DEVICES"] = "0"
os.environ["HSA_ENABLE_SDMA"] = "0"
os.environ["PYTORCH_HIP_ALLOC_CONF"] = "max_split_size_mb:128,garbage_collection_threshold:0.95,expandable_segments:True"
os.environ["HF_HOME"] = "/mnt/raid0/hf_cache"

import re
import torch
from flask import Flask, request, jsonify, Response, stream_with_context
from transformers import AutoModelForCausalLM, AutoProcessor, AutoTokenizer, TextIteratorStreamer

MODEL_PATH = "/mnt/raid0/qwen3.5-9b"
DEFAULT_PORT = 11434
MAX_INPUT_TOKENS = 6144   # tronca l'input prima di dare alla GPU (OOM prevention)

app = Flask(__name__)

# ── Stato globale ─────────────────────────────────────────────────────────────
_model = None
_tokenizer = None
_processor = None
_generate_lock = threading.Lock()


def _load_model():
    global _model, _tokenizer
    print(f"[MI50Server] Caricamento tokenizer da {MODEL_PATH} ...", flush=True)
    _tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
    print("[MI50Server] Caricamento modello (bfloat16, eager) ...", flush=True)
    _model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        attn_implementation="eager",   # no flash-attn: gfx906 non la supporta
    ).to("cuda")
    _model.eval()
    free_gb = torch.cuda.mem_get_info(0)[0] / 1024**3
    print(f"[MI50Server] ✅ Modello caricato. VRAM libera: {free_gb:.1f} GB", flush=True)


def _get_processor():
    global _processor
    if _processor is None:
        print("[MI50Server] Caricamento AutoProcessor (visione) ...", flush=True)
        _processor = AutoProcessor.from_pretrained(MODEL_PATH, trust_remote_code=True)
        print("[MI50Server] AutoProcessor caricato.", flush=True)
    return _processor


def _tokenize_and_truncate(text: str) -> dict:
    """Tokenizza e tronca a MAX_INPUT_TOKENS per evitare OOM."""
    inputs = _tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=MAX_INPUT_TOKENS,
    ).to("cuda")
    n = inputs["input_ids"].shape[1]
    if n == MAX_INPUT_TOKENS:
        print(f"[MI50Server] ⚠️  Input troncato a {MAX_INPUT_TOKENS} token", flush=True)
    else:
        print(f"[MI50Server] Input: {n} token", flush=True)
    return inputs


def _extract_thinking(raw: str) -> tuple[str, str]:
    m = re.search(r"<think>(.*?)</think>", raw, re.DOTALL)
    thinking = m.group(1).strip() if m else ""
    response = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return thinking, response


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return jsonify({"status": "ok", "model": "qwen3.5-9b", "device": "cuda"})


@app.post("/generate")
def generate():
    """
    Body JSON: {"messages": [...], "max_new_tokens": 1024}
    Risposta: {"thinking": str, "response": str, "raw": str}
    """
    data = request.get_json()
    messages = data.get("messages", [])
    max_new_tokens = int(data.get("max_new_tokens", 1024))

    with _generate_lock:
        text = _tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = _tokenize_and_truncate(text)

        with torch.no_grad():
            output_ids = _model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                temperature=None,
                top_p=None,
                pad_token_id=_tokenizer.eos_token_id,
            )

        input_len = inputs["input_ids"].shape[1]
        new_ids = output_ids[0][input_len:]
        raw = _tokenizer.decode(new_ids, skip_special_tokens=True)

    thinking, response = _extract_thinking(raw)
    return jsonify({"thinking": thinking, "response": response, "raw": raw})


@app.post("/generate_stream")
def generate_stream():
    """
    Streaming SSE di /generate.
    Body JSON: {"messages": [...], "max_new_tokens": 1024}
    """
    data = request.get_json()
    messages = data.get("messages", [])
    max_new_tokens = int(data.get("max_new_tokens", 1024))
    enable_thinking = bool(data.get("thinking", True))
    print(f"[MI50Server] /generate_stream enable_thinking={enable_thinking}", flush=True)

    # Rimuovi /no_think dai system prompt (gestito via enable_thinking)
    clean_messages = []
    for m in messages:
        if m.get("role") == "system" and m.get("content", "").startswith("/no_think"):
            m = {**m, "content": m["content"].replace("/no_think\n", "", 1).lstrip()}
        clean_messages.append(m)

    text = _tokenizer.apply_chat_template(
        clean_messages, tokenize=False, add_generation_prompt=True,
        enable_thinking=enable_thinking,
    )
    inputs = _tokenize_and_truncate(text)

    streamer = TextIteratorStreamer(
        _tokenizer, skip_prompt=True, skip_special_tokens=True
    )
    gen_kwargs = dict(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        temperature=None,
        top_p=None,
        pad_token_id=_tokenizer.eos_token_id,
        streamer=streamer,
    )

    def _run():
        with _generate_lock:
            with torch.no_grad():
                _model.generate(**gen_kwargs)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    def _sse():
        for token in streamer:
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"

    return Response(stream_with_context(_sse()), content_type="text/event-stream")


@app.post("/generate_with_images")
def generate_with_images():
    """
    Body JSON: {"messages": [...], "image_paths": [...], "max_new_tokens": 1024}
    Risposta: {"thinking": str, "response": str, "raw": str}
    """
    from PIL import Image

    data = request.get_json()
    messages = data.get("messages", [])
    image_paths = data.get("image_paths", [])
    max_new_tokens = int(data.get("max_new_tokens", 1024))

    proc = _get_processor()

    images = []
    for path in image_paths:
        try:
            images.append(Image.open(path).convert("RGB"))
        except Exception as e:
            print(f"[MI50Server] Impossibile caricare immagine {path}: {e}", flush=True)

    with _generate_lock:
        text = proc.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = proc(
            text=text,
            images=images if images else None,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_INPUT_TOKENS,
        ).to("cuda")

        input_len = inputs["input_ids"].shape[1]
        print(f"[MI50Server] /generate_with_images input_tokens={input_len}", flush=True)

        with torch.no_grad():
            output_ids = _model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                temperature=None,
                top_p=None,
                pad_token_id=_tokenizer.eos_token_id,
            )

        new_ids = output_ids[0][input_len:]
        raw = _tokenizer.decode(new_ids, skip_special_tokens=True)

    thinking, response = _extract_thinking(raw)
    return jsonify({"thinking": thinking, "response": response, "raw": raw})


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    _load_model()
    app.run(host="0.0.0.0", port=args.port, threaded=False)
