#!/bin/bash
# ============================================================
# start_servers.sh — Avvio sicuro MI50 + M40
#
# REGOLA: una GPU, un modello, un processo. Sempre.
#
# Comportamento:
#   1. Controlla se i server sono già healthy → se sì, skip tutto
#   2. Altrimenti: killa TUTTI i processi GPU (mi50, steering, llama),
#      aspetta che la VRAM si svuoti, poi carica i modelli
#
# Uso:
#   cd programmatore_di_arduini
#   source .venv/bin/activate
#   bash agent/start_servers.sh
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

MI50_PORT=11434
M40_PORT=11435
MI50_LOG="/tmp/mi50_server.log"
M40_LOG="/tmp/llama_server_m40_cuda.log"
M40_BINARY="/mnt/raid0/llama-cpp-m40/build_cuda/bin/llama-server"
M40_MODEL="/mnt/raid0/models-gguf/Qwen3.5-9B-Q5_K_M.gguf"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[>>]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*"; }

is_healthy() {
    curl -sf --max-time 3 "http://localhost:$1/health" >/dev/null 2>&1
}

wait_healthy() {
    local port=$1 label=$2 max=$3 elapsed=0
    while [ $elapsed -lt $max ]; do
        if is_healthy $port; then
            ok "$label pronto (${elapsed}s)"
            return 0
        fi
        sleep 5; elapsed=$((elapsed+5))
        echo "  attendo $label... ${elapsed}s/${max}s"
    done
    err "$label non risponde dopo ${max}s — controlla $MI50_LOG"
    return 1
}

# ── 1. Controlla se tutto è già healthy ───────────────────────────────────────
echo ""
echo "=== Verifica server ==="
MI50_OK=false; M40_OK=false
is_healthy $MI50_PORT && MI50_OK=true && ok "MI50 già healthy — skip"
is_healthy $M40_PORT  && M40_OK=true  && ok "M40  già healthy — skip"

if $MI50_OK && $M40_OK; then
    echo ""
    ok "Entrambi i server già attivi. Niente da fare."
    exit 0
fi

# ── 2. Kill di TUTTI i processi GPU ───────────────────────────────────────────
echo ""
echo "=== Kill processi GPU ==="
GPU_PROCS=$(ps aux | grep -E "mi50_server\.py|steering_server\.py|llama-server" | grep -v grep | awk '{print $2}')
if [ -n "$GPU_PROCS" ]; then
    warn "Killo: $(echo $GPU_PROCS | tr '\n' ' ')"
    echo "$GPU_PROCS" | xargs kill -9 2>/dev/null || true
    sleep 3
    ok "Processi GPU killati"
else
    ok "Nessun processo GPU attivo"
fi

# ── 3. M40 ────────────────────────────────────────────────────────────────────
if ! $M40_OK; then
    echo ""
    echo "=== Avvio M40 (llama-server) ==="
    export LD_LIBRARY_PATH=/mnt/raid0/llama-cpp-m40/build_cuda/bin:/usr/local/cuda-11.8/lib64:/usr/lib/x86_64-linux-gnu
    OMP_NUM_THREADS=8 "$M40_BINARY" \
        --model "$M40_MODEL" \
        --host 0.0.0.0 --port $M40_PORT \
        --ctx-size 16384 --parallel 1 --threads 8 \
        --n-gpu-layers 99 --log-disable > "$M40_LOG" 2>&1 &
    echo $! > /tmp/llama_server_m40.pid
    warn "M40 avviato (PID $!) — attendo..."
    wait_healthy $M40_PORT "M40" 120
fi

# ── 4. MI50 (Docker) ──────────────────────────────────────────────────────────
if ! $MI50_OK; then
    echo ""
    echo "=== Avvio MI50 (Qwen3.5-9B — Docker) ==="
    warn "Caricamento modello (~10 min prima volta, ~30s se già in RAM)..."
    cd "$PROJECT_DIR"
    bash docker/run_mi50.sh
fi

# ── 5. Riepilogo ──────────────────────────────────────────────────────────────
echo ""
echo "=== Stato finale ==="
is_healthy $MI50_PORT && ok "MI50 OK" || err "MI50 NON OK — log: $MI50_LOG"
is_healthy $M40_PORT  && ok "M40  OK" || err "M40  NON OK — log: $M40_LOG"
echo ""
