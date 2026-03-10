#!/usr/bin/env bash
# Avvio rapido Qwen3.5-9B su MI50 + M40
# Uso: bash avvia_qwen35.sh [mi50|m40|both]
#
# MI50: steering server (porta 8010) NON viene toccato — Qwen3.5 gira standalone
# M40: llama-server porta 11436 (non interferisce con l'11435 esistente)

VENV="/home/lele/codex-openai/programmatore_di_arduini/.venv/bin/python"
LLAMA_SERVER="/mnt/raid0/llama-cpp-m40/build_cuda/bin/llama-server"
GGUF="/mnt/raid0/models-gguf/Qwen3.5-9B-Q5_K_M.gguf"
HF_MODEL="/mnt/raid0/qwen3.5-9b"
LD_PATH="/mnt/raid0/llama-cpp-m40/build_cuda/bin:/usr/local/cuda-11.8/lib64:/usr/lib/x86_64-linux-gnu"

MODE=${1:-both}

# ── Funzioni ──────────────────────────────────────────────────────────────────

start_m40() {
    echo "→ Avvio llama-server Qwen3.5-9B-Q5_K_M su M40 (porta 11436)..."
    if [ ! -f "$GGUF" ]; then
        echo "  ❌ GGUF non trovato: $GGUF"
        echo "     Download: tail -f /tmp/download_qwen35_m40.log"
        return 1
    fi

    LD_LIBRARY_PATH="$LD_PATH" \
    OMP_NUM_THREADS=8 \
    CUDA_VISIBLE_DEVICES=0 \
    HIP_VISIBLE_DEVICES=-1 \
    "$LLAMA_SERVER" \
        --model "$GGUF" \
        --host 0.0.0.0 \
        --port 11436 \
        --ctx-size 4096 \
        --threads 8 \
        --n-gpu-layers 99 \
        --log-disable &

    echo $! > /tmp/llama_m40_qwen35.pid
    echo "  PID: $(cat /tmp/llama_m40_qwen35.pid)"

    echo -n "  Attendo avvio..."
    for i in $(seq 1 30); do
        sleep 1
        if curl -s http://localhost:11436/health > /dev/null 2>&1; then
            echo " pronto!"
            echo "  ✅ M40 Qwen3.5 su http://localhost:11436"
            return 0
        fi
        echo -n "."
    done
    echo " TIMEOUT"
    return 1
}

start_mi50_chat() {
    echo "→ Test MI50 Qwen3.5-9B..."
    if [ ! -d "$HF_MODEL" ]; then
        echo "  ❌ Modello non trovato: $HF_MODEL"
        echo "     Download: tail -f /tmp/download_qwen35_mi50.log"
        return 1
    fi
    echo "  Modello trovato: $HF_MODEL"
    echo "  Per usarlo da Python:"
    echo "    $VENV test_mi50_qwen35.py"
}

stop_m40() {
    if [ -f /tmp/llama_m40_qwen35.pid ]; then
        kill "$(cat /tmp/llama_m40_qwen35.pid)" 2>/dev/null
        rm /tmp/llama_m40_qwen35.pid
        echo "M40 Qwen3.5 fermato."
    else
        echo "Nessun processo M40 Qwen3.5 attivo."
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

case "$MODE" in
    mi50)
        start_mi50_chat
        ;;
    m40)
        start_m40
        ;;
    stop)
        stop_m40
        ;;
    test)
        echo "=== Test MI50 ==="
        "$VENV" test_mi50_qwen35.py
        echo ""
        echo "=== Test M40 ==="
        "$VENV" test_m40_qwen35.py
        ;;
    both|*)
        start_mi50_chat
        echo ""
        start_m40
        echo ""
        echo "Status:"
        curl -s http://localhost:11436/health && echo " ← M40 Qwen3.5 (porta 11436)"
        ;;
esac
