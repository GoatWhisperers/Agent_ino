#!/usr/bin/env python3
"""
Test Qwen3.5-9B-Q5_K_M su M40 (NVIDIA Tesla, 11.5GB VRAM, CUDA sm_52)
tramite llama-server CUDA compilato con CUDA 11.8 + sm_52.

NOTA: lanciare quando la M40 è libera (nessun altro llama-server attivo).
      Su questo server si lavora su un progetto alla volta.

Uso: /home/lele/codex-openai/project_jedi/.venv/bin/python test_m40_qwen35.py
"""

import os
import sys
import time
import subprocess
import requests

GGUF_PATH = "/mnt/raid0/models-gguf/Qwen3.5-9B-Q5_K_M.gguf"
LLAMA_SERVER = "/mnt/raid0/llama-cpp-m40/build_cuda/bin/llama-server"
PORT = 11435
PID_FILE = "/tmp/llama_m40_qwen35.pid"
LD_PATH = (
    "/mnt/raid0/llama-cpp-m40/build_cuda/bin"
    ":/usr/local/cuda-11.8/lib64"
    ":/usr/lib/x86_64-linux-gnu"
)


def check_prerequisites():
    errors = []
    if not os.path.isfile(GGUF_PATH):
        errors.append(f"❌ GGUF non trovato: {GGUF_PATH}")
    if not os.path.isfile(LLAMA_SERVER):
        errors.append(f"❌ llama-server non trovato: {LLAMA_SERVER}")
    if errors:
        for e in errors:
            print(e)
        sys.exit(1)
    size_gb = os.path.getsize(GGUF_PATH) / 1e9
    print(f"✅ GGUF: {GGUF_PATH} ({size_gb:.2f} GB)")


def start_llama_server():
    print(f"\nAvvio llama-server Qwen3.5 su porta {PORT}...")
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = LD_PATH
    env["OMP_NUM_THREADS"] = "8"
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env["HIP_VISIBLE_DEVICES"] = "-1"

    proc = subprocess.Popen(
        [LLAMA_SERVER,
         "--model", GGUF_PATH,
         "--host", "0.0.0.0",
         "--port", str(PORT),
         "--ctx-size", "4096",
         "--threads", "8",
         "--n-gpu-layers", "99",
         "--log-disable"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    print(f"  PID: {proc.pid}")
    return proc


def wait_for_server(timeout=40):
    print(f"  Attendo server...", end="", flush=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(f"http://localhost:{PORT}/health", timeout=2)
            if r.status_code == 200:
                print(f" pronto in {time.time()-t0:.1f}s")
                return True
        except requests.exceptions.ConnectionError:
            pass
        print(".", end="", flush=True)
        time.sleep(1)
    print(" TIMEOUT")
    return False


def chat(messages, max_tokens=512, temperature=0.1):
    resp = requests.post(
        f"http://localhost:{PORT}/v1/chat/completions",
        json={"model": "qwen3.5", "messages": messages,
              "max_tokens": max_tokens, "temperature": temperature, "stream": False},
        timeout=120
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"], data.get("usage", {})


def stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    print("  Server fermato.")


def main():
    print("=" * 60)
    print("TEST QWEN3.5-9B-Q5_K_M su M40")
    print("=" * 60)
    check_prerequisites()

    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        print(f"  GPU: {r.stdout.strip()}")
    except Exception:
        pass

    proc = start_llama_server()
    if not wait_for_server():
        print("❌ Server non risponde.")
        stop_server(proc)
        sys.exit(1)

    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        print(f"  GPU dopo caricamento: {r.stdout.strip()}")
    except Exception:
        pass

    print("\n--- TEST 1: sketch LED lampeggiante ---")
    t0 = time.time()
    resp1, usage1 = chat([
        {"role": "system", "content": "Sei un esperto di Arduino. Rispondi in italiano."},
        {"role": "user",   "content": "Scrivi uno sketch Arduino per far lampeggiare un LED sul pin 13 ogni 500ms. Spiega ogni riga."}
    ])
    t1 = time.time() - t0
    n1 = usage1.get("completion_tokens", "?")
    print(f"  {n1} token in {t1:.1f}s ({n1/t1:.1f} tok/s)" if isinstance(n1, int) else f"  {t1:.1f}s")
    print(f"\n{resp1}")

    print("\n--- TEST 2: sensore DHT22 ---")
    t0 = time.time()
    resp2, usage2 = chat([
        {"role": "system", "content": "Sei un esperto di Arduino. Rispondi in italiano."},
        {"role": "user",   "content": "Come leggo temperatura e umidità da un sensore DHT22 con Arduino? Codice completo."}
    ])
    t2 = time.time() - t0
    n2 = usage2.get("completion_tokens", "?")
    print(f"  {n2} token in {t2:.1f}s ({n2/t2:.1f} tok/s)" if isinstance(n2, int) else f"  {t2:.1f}s")
    print(f"\n{resp2}")

    print("\n" + "=" * 60)
    print("✅ TEST M40 COMPLETATO")
    print("=" * 60)

    stop_server(proc)


if __name__ == "__main__":
    main()
