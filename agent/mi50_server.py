"""
MI50 Server — Qwen3.5-9B persistente su ROCm.

Carica il modello una volta sola e rimane in VRAM per tutta la sessione.
Espone un'API HTTP identica all'interfaccia di m40_client.py.

Avvio:
    (dentro Docker — gestito da run_mi50.sh / start_servers.sh)

Verifica:
    curl http://localhost:11434/health

Limiti di contesto:
    MAX_INPUT_TOKENS = 24576 — input troncato a questo valore
    max_new_tokens default = 8192
    Con attn_implementation='sdpa' (PyTorch builtin, no Triton, no flash-attn library):
      - Memoria attenzione O(N·√N) invece di O(N²) — a 24K tok ~2GB invece di 33GB
      - flash_sdp disabilitato esplicitamente (gfx906 non supporta FA2)
      - efficient_sdp e math_sdp attivi — nessun SIGSEGV da Triton
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
from transformers import Qwen3_5ForConditionalGeneration

MODEL_PATH = "/mnt/raid0/qwen3.5-9b"
DEFAULT_PORT = 11434
MAX_INPUT_TOKENS = 24576  # tronca l'input prima di dare alla GPU

app = Flask(__name__)

# ── Stato globale ─────────────────────────────────────────────────────────────
_model = None
_tokenizer = None
_processor = None
_generate_lock = threading.Lock()   # una sola generate alla volta (GPU è single-tenant)
_processor_lock = threading.Lock()  # carica processor una sola volta


_eos_token_ids: list[int] = []


def _load_model():
    global _model, _tokenizer, _eos_token_ids
    print(f"[MI50Server] Caricamento tokenizer da {MODEL_PATH} ...", flush=True)
    _tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
    # sdpa = PyTorch builtin memory-efficient attention, no Triton, no flash-attn library
    # flash_sdp disabilitato: gfx906 non supporta FA2 (SIGSEGV)
    # efficient_sdp + math_sdp attivi: safe su gfx906, memoria O(N·√N)
    torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_mem_efficient_sdp(True)
    torch.backends.cuda.enable_math_sdp(True)
    print("[MI50Server] Caricamento modello (bfloat16, sdpa) ...", flush=True)
    # Usa ForConditionalGeneration per abilitare la visione (pixel_values, image_grid_thw).
    # Retrocompatibile con generazione solo testo — stessa interfaccia, più funzionalità.
    _model = Qwen3_5ForConditionalGeneration.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        attn_implementation="sdpa",    # memory-efficient, no Triton, safe su gfx906
    ).to("cuda")
    _model.eval()
    # Stop tokens: <|endoftext|> + <|im_end|> (fine turno assistant in Qwen)
    # Senza <|im_end|> il modello continua a generare turni finti (run-ahead hallucination)
    eos = set()
    for tok in ["<|endoftext|>", "<|im_end|>", "<|end|>"]:
        tid = _tokenizer.convert_tokens_to_ids(tok)
        if isinstance(tid, int) and tid != _tokenizer.unk_token_id:
            eos.add(tid)
    if _tokenizer.eos_token_id is not None:
        eos.add(_tokenizer.eos_token_id)
    _eos_token_ids = sorted(eos)
    print(f"[MI50Server] EOS token ids: {_eos_token_ids}", flush=True)
    free_gb = torch.cuda.mem_get_info(0)[0] / 1024**3
    print(f"[MI50Server] ✅ Modello caricato. VRAM libera: {free_gb:.1f} GB", flush=True)


def _get_processor():
    global _processor
    with _processor_lock:
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
                eos_token_id=_eos_token_ids or None,
                pad_token_id=(_eos_token_ids[0] if _eos_token_ids else _tokenizer.eos_token_id),
            )

        input_len = inputs["input_ids"].shape[1]
        new_ids = output_ids[0][input_len:]
        raw = _tokenizer.decode(new_ids, skip_special_tokens=True)

    torch.cuda.empty_cache()
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
        eos_token_id=_eos_token_ids or None,
        pad_token_id=(_eos_token_ids[0] if _eos_token_ids else _tokenizer.eos_token_id),
        streamer=streamer,
    )

    def _run():
        with _generate_lock:
            with torch.no_grad():
                _model.generate(**gen_kwargs)
        # Libera KV cache e frammentazione VRAM dopo ogni generazione
        torch.cuda.empty_cache()

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

    pil_images = []
    for path in image_paths:
        try:
            pil_images.append(Image.open(path).convert("RGB"))
        except Exception as e:
            print(f"[MI50Server] Impossibile caricare immagine {path}: {e}", flush=True)

    # Qwen3-VL richiede che le immagini siano nel content come liste strutturate
    # ({"type":"image","image":img}, {"type":"text","text":"..."})
    # NON come messaggi plain text con le immagini passate separatamente.
    if pil_images:
        vision_messages = []
        for msg in messages:
            if msg["role"] == "user":
                content = [{"type": "image", "image": img} for img in pil_images]
                text_content = msg.get("content", "")
                if text_content:
                    content.append({"type": "text", "text": text_content})
                vision_messages.append({"role": "user", "content": content})
            else:
                vision_messages.append(msg)
    else:
        vision_messages = messages

    with _generate_lock:
        text = proc.apply_chat_template(
            vision_messages, tokenize=False, add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = proc(
            text=text,
            images=pil_images if pil_images else None,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_INPUT_TOKENS,
        ).to("cuda")

        input_len = inputs["input_ids"].shape[1]
        print(f"[MI50Server] /generate_with_images input_tokens={input_len}", flush=True)

        # Passa tutto al modello eccetto mm_token_type_ids (causa errori su Qwen3.5-VL).
        # pixel_values e image_grid_thw sono necessari per la visione e vanno via **kwargs.
        _VISION_BLACKLIST = {"mm_token_type_ids"}
        gen_inputs = {k: v for k, v in inputs.items() if k not in _VISION_BLACKLIST}

        with torch.no_grad():
            output_ids = _model.generate(
                **gen_inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                temperature=None,
                top_p=None,
                eos_token_id=_eos_token_ids or None,
                pad_token_id=(_eos_token_ids[0] if _eos_token_ids else _tokenizer.eos_token_id),
            )

        new_ids = output_ids[0][input_len:]
        raw = _tokenizer.decode(new_ids, skip_special_tokens=True)

    torch.cuda.empty_cache()
    thinking, response = _extract_thinking(raw)
    return jsonify({"thinking": thinking, "response": response, "raw": raw})


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    _load_model()
    # threaded=True: Flask gestisce health check anche durante streaming
    # _generate_lock garantisce che la GPU faccia una sola generate alla volta
    app.run(host="0.0.0.0", port=args.port, threaded=True)
