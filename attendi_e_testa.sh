#!/usr/bin/env bash
# Aspetta che i download di Qwen3.5 finiscano e poi lancia i test.
# Uso: bash attendi_e_testa.sh
# Log: tail -f /tmp/attendi_e_testa.log

VENV="/home/lele/codex-openai/programmatore_di_arduini/.venv/bin/python"
MI50_MODEL="/mnt/raid0/qwen3.5-9b"
GGUF_FILE="/mnt/raid0/models-gguf/Qwen3.5-9B-Q5_K_M.gguf"
GGUF_EXPECTED_SIZE=6500000000   # ~6.5 GB (soglia minima, file reale ~6.578 GB)
MI50_SHARD1="model.safetensors-00001-of-00004.safetensors"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="/tmp/attendi_e_testa.log"

log() {
    echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"
}

check_mi50_complete() {
    # Controlla che tutti e 4 gli shard siano presenti e > 1GB ciascuno
    local count=0
    for i in 1 2 3 4; do
        local f="$MI50_MODEL/$MI50_SHARD1"
        f="${f/00001/$(printf '%05d' $i)}"
        if [ -f "$f" ] && [ "$(stat -c%s "$f")" -gt 1000000000 ]; then
            ((count++))
        fi
    done
    [ "$count" -eq 4 ]
}

check_gguf_complete() {
    # Controlla che il GGUF sia presente e abbia la dimensione attesa
    [ -f "$GGUF_FILE" ] && [ "$(stat -c%s "$GGUF_FILE")" -gt "$GGUF_EXPECTED_SIZE" ]
}

wait_for_download() {
    local name="$1"
    local check_fn="$2"
    local interval=30
    local elapsed=0
    local max_wait=7200  # 2 ore max

    log "Attendo completamento download: $name"
    while ! $check_fn; do
        sleep "$interval"
        elapsed=$((elapsed + interval))
        # Mostra progresso
        if [ "$name" = "MI50" ]; then
            local done_bytes=$(find "$MI50_MODEL/.cache" -name "*.incomplete" -exec stat -c%s {} + 2>/dev/null | awk '{sum+=$1}END{print sum+0}')
            local done_gb=$(echo "scale=1; $done_bytes/1073741824" | bc 2>/dev/null || echo "?")
            log "  MI50: ~${done_gb} GB / ~19 GB scaricati (${elapsed}s)"
        else
            local gguf_size=$(stat -c%s "$GGUF_FILE" 2>/dev/null || echo 0)
            local done_gb=$(echo "scale=2; $gguf_size/1073741824" | bc 2>/dev/null || echo "?")
            log "  GGUF: ${done_gb} GB / 6.58 GB scaricati (${elapsed}s)"
        fi
        if [ "$elapsed" -ge "$max_wait" ]; then
            log "❌ TIMEOUT dopo ${max_wait}s per $name"
            return 1
        fi
    done
    log "✅ $name download completato!"
    return 0
}

# ── Main ─────────────────────────────────────────────────────────────────────

log "=== AVVIO SCRIPT ATTENDI E TESTA ==="
log "MI50 model: $MI50_MODEL"
log "M40 GGUF: $GGUF_FILE"

# Aspetta entrambi i download
wait_for_download "GGUF" check_gguf_complete || { log "GGUF fallito, esco"; exit 1; }
wait_for_download "MI50" check_mi50_complete || { log "MI50 fallito, esco"; exit 1; }

log ""
log "=== ENTRAMBI I DOWNLOAD COMPLETATI ==="
log ""

# Test M40 prima (più veloce)
log "=== TEST M40 ==="
cd "$SCRIPT_DIR"
"$VENV" test_m40_qwen35.py 2>&1 | tee -a "$LOG"
M40_EXIT=${PIPESTATUS[0]}

log ""
log "M40 test exit code: $M40_EXIT"

# Test MI50
log ""
log "=== TEST MI50 ==="
"$VENV" test_mi50_qwen35.py 2>&1 | tee -a "$LOG"
MI50_EXIT=${PIPESTATUS[0]}

log ""
log "MI50 test exit code: $MI50_EXIT"

# Risultato finale
log ""
log "=== RIEPILOGO FINALE ==="
if [ "$M40_EXIT" -eq 0 ] && [ "$MI50_EXIT" -eq 0 ]; then
    log "✅ TUTTI I TEST PASSATI"
elif [ "$M40_EXIT" -ne 0 ] && [ "$MI50_EXIT" -ne 0 ]; then
    log "❌ ENTRAMBI I TEST FALLITI"
elif [ "$M40_EXIT" -ne 0 ]; then
    log "⚠️  M40 fallito, MI50 OK"
else
    log "⚠️  MI50 fallito, M40 OK"
fi

log "Log completo: $LOG"
