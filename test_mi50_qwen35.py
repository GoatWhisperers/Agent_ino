#!/usr/bin/env python3
"""
Test Qwen3.5-9B su MI50 (AMD, 32GB VRAM, ROCm 3.11)
Uso: /home/lele/codex-openai/project_jedi/.venv/bin/python test_mi50_qwen35.py
"""

import os
import sys
import time

# ── env vars OBBLIGATORIE prima di import torch ──────────────────────────────
os.environ["HSA_OVERRIDE_GFX_VERSION"] = "9.0.6"
os.environ["HIP_VISIBLE_DEVICES"] = "0"
os.environ["HSA_ENABLE_SDMA"] = "0"
os.environ["PYTORCH_HIP_ALLOC_CONF"] = (
    "max_split_size_mb:128,garbage_collection_threshold:0.95,expandable_segments:True"
)
os.environ["HF_HOME"] = "/mnt/raid0/hf_cache"
os.environ["TRANSFORMERS_CACHE"] = "/mnt/raid0/hf_cache/transformers"
# ─────────────────────────────────────────────────────────────────────────────

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_PATH = "/mnt/raid0/qwen3.5-9b"

def check_model_exists():
    if not os.path.isdir(MODEL_PATH):
        print(f"❌ Modello non trovato: {MODEL_PATH}")
        print("   Aspetta che il download finisca. Controlla: tail -f /tmp/download_qwen35_mi50.log")
        sys.exit(1)
    # Controlla che ci siano file safetensors
    safetensors = [f for f in os.listdir(MODEL_PATH) if f.endswith(".safetensors")]
    if not safetensors:
        print(f"❌ Nessun file safetensors in {MODEL_PATH}")
        sys.exit(1)
    print(f"✅ Modello trovato: {len(safetensors)} file safetensors")

def print_vram_status(label=""):
    if torch.cuda.is_available():
        used = torch.cuda.memory_allocated() / 1e9
        total = torch.cuda.get_device_properties(0).total_memory / 1e9
        free = (torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated()) / 1e9
        print(f"  VRAM {label}: {used:.1f} GB usati / {total:.1f} GB totali ({free:.1f} GB liberi)")

def main():
    print("=" * 60)
    print("TEST QWEN3.5-9B su MI50 (ROCm)")
    print("=" * 60)

    check_model_exists()

    print(f"\nDevice: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"CUDA disponibile: {torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        print("❌ CUDA (ROCm) non disponibile! Controlla env vars HSA_*")
        sys.exit(1)

    print_vram_status("prima del caricamento")

    # ── Carica tokenizer ──────────────────────────────────────────────────────
    print(f"\nCaricamento tokenizer da {MODEL_PATH}...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=False)
    print(f"✅ Tokenizer caricato. Vocab size: {tokenizer.vocab_size}")

    # ── Carica modello in RAM, poi sposta su VRAM (pattern corretto per MI50) ─
    print("\nCaricamento modello in RAM (pattern RAM-first)...")
    t0 = time.time()
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.bfloat16,
        attn_implementation="sdpa",
        trust_remote_code=False
    )
    t_load = time.time() - t0
    print(f"  Modello in RAM in {t_load:.1f}s")

    print("Spostamento su GPU MI50...")
    t0 = time.time()
    model = model.to("cuda")
    model.eval()
    torch.cuda.empty_cache()
    t_gpu = time.time() - t0
    print(f"  Trasferimento GPU in {t_gpu:.1f}s")

    print_vram_status("dopo caricamento")
    print(f"  Device parametri: {next(model.parameters()).device}")

    # ── Test 1: prompt semplice per programmatore Arduino ─────────────────────
    print("\n" + "-" * 40)
    print("TEST 1: Sketch Arduino LED lampeggiante")
    print("-" * 40)

    messages = [
        {
            "role": "system",
            "content": (
                "Sei un esperto di programmazione Arduino e microcontrollori. "
                "Rispondi in italiano con codice chiaro e spiegazioni concise."
            )
        },
        {
            "role": "user",
            "content": "Scrivi uno sketch Arduino per far lampeggiare un LED sul pin 13 ogni 500ms. Spiega ogni riga."
        }
    ]

    # Applica chat template
    if hasattr(tokenizer, "apply_chat_template"):
        text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
    else:
        # Fallback per modelli senza template
        text = f"Sistema: {messages[0]['content']}\nUtente: {messages[1]['content']}\nAssistente:"

    inputs = tokenizer(text, return_tensors="pt").to("cuda")
    n_prompt_tokens = inputs["input_ids"].shape[1]
    print(f"  Token prompt: {n_prompt_tokens}")

    t0 = time.time()
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=False,      # greedy per test deterministico
            temperature=1.0,
            repetition_penalty=1.05
        )
    t_gen = time.time() - t0

    new_tokens = output_ids[0][n_prompt_tokens:]
    response1 = tokenizer.decode(new_tokens, skip_special_tokens=True)
    n_new = len(new_tokens)
    tok_per_sec = n_new / t_gen

    print(f"  Token generati: {n_new} in {t_gen:.1f}s ({tok_per_sec:.1f} tok/s)")
    print(f"\nRisposta:\n{response1}")

    # ── Test 2: lettura sensore (prompt più complesso) ─────────────────────────
    print("\n" + "-" * 40)
    print("TEST 2: Sensor DHT22 + Serial Monitor")
    print("-" * 40)

    messages2 = [
        {"role": "system", "content": "Sei un esperto di Arduino. Rispondi in italiano."},
        {"role": "user",   "content": "Come leggo temperatura e umidità da un sensore DHT22 con Arduino Uno? Mostra il codice completo."}
    ]

    if hasattr(tokenizer, "apply_chat_template"):
        text2 = tokenizer.apply_chat_template(messages2, tokenize=False, add_generation_prompt=True)
    else:
        text2 = f"Sistema: {messages2[0]['content']}\nUtente: {messages2[1]['content']}\nAssistente:"

    inputs2 = tokenizer(text2, return_tensors="pt").to("cuda")

    t0 = time.time()
    with torch.no_grad():
        output_ids2 = model.generate(
            **inputs2,
            max_new_tokens=512,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
            repetition_penalty=1.05
        )
    t_gen2 = time.time() - t0

    new_tokens2 = output_ids2[0][inputs2["input_ids"].shape[1]:]
    response2 = tokenizer.decode(new_tokens2, skip_special_tokens=True)
    tok_per_sec2 = len(new_tokens2) / t_gen2

    print(f"  Token generati: {len(new_tokens2)} in {t_gen2:.1f}s ({tok_per_sec2:.1f} tok/s)")
    print(f"\nRisposta:\n{response2}")

    # ── Riepilogo finale ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RIEPILOGO TEST MI50")
    print("=" * 60)
    print_vram_status("finale")
    print(f"  Velocità media: {(tok_per_sec + tok_per_sec2) / 2:.1f} tok/s")
    print("✅ TEST COMPLETATO CON SUCCESSO")

    # Pulizia
    del model
    import gc
    gc.collect()
    torch.cuda.empty_cache()

if __name__ == "__main__":
    main()
