#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

MI50_HEALTH="http://127.0.0.1:11434/health"
M40_HEALTH="http://127.0.0.1:11436/health"
DASH_HEALTH="http://127.0.0.1:7700/health"
MEM_HEALTH="http://127.0.0.1:7701/health"

M40_BIN="/mnt/raid0/llama-cpp-m40/build_cuda/bin/llama-server"
M40_MODEL="/mnt/raid0/models-gguf/Qwen3.5-9B-Q5_K_M.gguf"
M40_LOG="/tmp/llama_qwen_11436.log"
DASH_LOG="/tmp/dashboard_7700.log"

PI_HOST="${PI_HOST:-192.168.1.167}"
PI_USER="${PI_USER:-lele}"
PI_PASS="${PI_PASS:-}"
ETH_IFACE="${ETH_IFACE:-eth0}"
RUN_TASK="${RUN_TASK:-}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[..]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*"; }

usage() {
  cat <<EOF
Uso:
  bash agent/start_one.sh [--task "testo task"] [--task-file path.txt]

Opzioni:
  --task "..."        Lancia tool_agent con questo task dopo i check
  --task-file FILE    Legge il task da file (es: PROMPT_DHT11_OLED.txt)

Env opzionali:
  PI_HOST   (default: 192.168.1.167)
  PI_USER   (default: lele)
  PI_PASS   password SSH per check Raspberry (se vuoto, check Pi saltati)
  ETH_IFACE (default: eth0)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)
      RUN_TASK="$2"; shift 2 ;;
    --task-file)
      RUN_TASK="$(cat "$2")"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      err "Argomento non riconosciuto: $1"; usage; exit 1 ;;
  esac
done

health_up() {
  curl -fsS --max-time 3 "$1" >/dev/null 2>&1
}

wait_health() {
  local url="$1" label="$2" max_sec="${3:-120}" waited=0
  while (( waited < max_sec )); do
    if health_up "$url"; then
      ok "$label pronto (${waited}s)"
      return 0
    fi
    sleep 2
    waited=$((waited+2))
  done
  err "$label non risponde (${max_sec}s)"
  return 1
}

cd "$PROJECT_DIR"
source .venv/bin/activate

echo ""
echo "=== 1) Pulizia processi ==="
pkill -f "agent/tool_agent.py" || true
pkill -f "agent/dashboard.py" || true
pkill -f "llama-cpp-m40/build_cuda/bin/llama-server" || true
docker stop mi50-server >/dev/null 2>&1 || true
sleep 2
ok "Processi principali fermati"

echo ""
echo "=== 2) Rete locale per Raspberry ==="
if sudo -n true >/dev/null 2>&1; then
  sudo ip link set "$ETH_IFACE" up || true
  sudo dhcpcd "$ETH_IFACE" || true
  SRC_IP="$(ip -o -4 addr show "$ETH_IFACE" | awk '{print $4}' | cut -d/ -f1 | head -n1 || true)"
  if [[ -n "$SRC_IP" ]]; then
    sudo ip route replace "${PI_HOST}/32" dev "$ETH_IFACE" src "$SRC_IP" metric 5 || true
    ok "Route forzata ${PI_HOST}/32 via ${ETH_IFACE} src ${SRC_IP}"
  else
    warn "IP su ${ETH_IFACE} non trovato: route host Pi non applicata"
  fi
else
  warn "sudo non passwordless: salto fix rete automatico"
fi

echo ""
echo "=== 3) Avvio MI50 (Docker 11434) ==="
bash docker/run_mi50.sh
wait_health "$MI50_HEALTH" "MI50" 90

echo ""
echo "=== 4) Avvio M40 Qwen (11436) ==="
export LD_LIBRARY_PATH=/mnt/raid0/llama-cpp-m40/build_cuda/bin:/usr/local/cuda-11.8/lib64:/usr/lib/x86_64-linux-gnu
OMP_NUM_THREADS=8 "$M40_BIN" \
  --model "$M40_MODEL" \
  --host 0.0.0.0 --port 11436 --ctx-size 16384 --parallel 1 --threads 8 \
  --n-gpu-layers 99 --log-disable > "$M40_LOG" 2>&1 &
echo $! > /tmp/llama_qwen_11436.pid
wait_health "$M40_HEALTH" "M40 Qwen" 120

echo ""
echo "=== 5) Avvio dashboard (7700) ==="
python agent/dashboard.py > "$DASH_LOG" 2>&1 &
echo $! > /tmp/dashboard_7700.pid
wait_health "$DASH_HEALTH" "Dashboard" 30
ok "Dashboard: http://localhost:7700"

echo ""
echo "=== 6) Check toolchain locale ==="
python - <<'PY'
import requests
from agent.compiler import check_libraries
print("MI50 health:", requests.get("http://127.0.0.1:11434/health", timeout=5).json())
print("M40 health:", requests.get("http://127.0.0.1:11436/health", timeout=5).json())
print("Lib Arduino:", check_libraries(["Adafruit_SSD1306","Adafruit_GFX_Library","Adafruit_BusIO"]))
PY
health_up "$MEM_HEALTH" && ok "Memory server 7701 OK" || warn "Memory server 7701 non raggiungibile"

echo ""
echo "=== 7) Check Raspberry / componenti ==="
if [[ -n "$PI_PASS" ]] && command -v sshpass >/dev/null 2>&1; then
  sshpass -p "$PI_PASS" ssh -T -o StrictHostKeyChecking=no -o ConnectTimeout=10 "${PI_USER}@${PI_HOST}" \
    "echo SSH_OK; hostname; ls /dev/ttyUSB* 2>/dev/null || true; ls /dev/video* 2>/dev/null || true"
  python - <<'PY'
from agent.remote_uploader import is_reachable, check_pio_libraries
from agent.grab import grab_now
print("Pi reachable:", is_reachable())
print("PIO libs:", check_pio_libraries(["Adafruit SSD1306", "Adafruit GFX Library"]))
print("Grab:", grab_now(n_frames=1))
PY
else
  warn "PI_PASS non impostata (o sshpass assente): salto check Raspberry"
  warn "Per abilitarli: PI_PASS='***' bash agent/start_one.sh"
fi

echo ""
ok "Bootstrap completo"

if [[ -n "$RUN_TASK" ]]; then
  echo ""
  echo "=== 8) Avvio tool_agent ==="
  python agent/tool_agent.py "$RUN_TASK" --fqbn esp32:esp32:esp32
else
  warn "Nessun task fornito: stack pronta. Avvia tu:"
  echo "python agent/tool_agent.py \"<task>\" --fqbn esp32:esp32:esp32"
fi

