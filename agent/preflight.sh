#!/bin/bash
# ============================================================
# preflight.sh — Check completo + avvio automatico di tutti i servizi
#
# Uso:
#   cd programmatore_di_arduini
#   source .venv/bin/activate
#   bash agent/preflight.sh
#
# Esegue in ordine:
#   1. MI50 + M40       → start_servers.sh
#   2. Dashboard 7700   → avvia se down
#   3. Memory server    → docker start se down
#   4. Raspberry Pi     → ping + SSH porta seriale
#   5. Webcam           → grab_now(1)
#   6. Librerie locali  → arduino-cli
#   7. Librerie Pi      → PlatformIO
#   8. Semaforo finale
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✅  $*${NC}"; }
warn() { echo -e "  ${YELLOW}⚠️   $*${NC}"; }
err()  { echo -e "  ${RED}❌  $*${NC}"; }
hdr()  { echo -e "\n${BOLD}=== $* ===${NC}"; }

# Array semaforo finale
declare -a RESULTS=()
pass() { RESULTS+=("${GREEN}✅  $*${NC}"); }
fail() { RESULTS+=("${RED}❌  $*${NC}"); }

cd "$PROJECT_DIR"

# ── STEP 1: MI50 + M40 ───────────────────────────────────────────────────────
hdr "STEP 1 — MI50 + M40"
bash agent/start_servers.sh

if curl -sf --max-time 3 http://localhost:11434/health >/dev/null 2>&1; then
    pass "MI50 (porta 11434)"
else
    fail "MI50 (porta 11434) — non risponde"
fi

if curl -sf --max-time 3 http://localhost:11435/health >/dev/null 2>&1; then
    pass "M40 (porta 11435)"
else
    fail "M40 (porta 11435) — non risponde"
fi

# ── STEP 2: Dashboard 7700 ───────────────────────────────────────────────────
hdr "STEP 2 — Dashboard (porta 7700)"
if curl -sf --max-time 5 http://localhost:7700/ >/dev/null 2>&1; then
    ok "Dashboard già attiva"
    pass "Dashboard (porta 7700)"
else
    warn "Dashboard down — avvio..."
    nohup python3 -c "
import sys; sys.path.insert(0, '.')
import agent.dashboard as d, time
d.start()
while True: time.sleep(60)
" > /tmp/dashboard.log 2>&1 &
    sleep 4
    if curl -sf --max-time 5 http://localhost:7700/ >/dev/null 2>&1; then
        ok "Dashboard avviata"
        pass "Dashboard (porta 7700)"
    else
        err "Dashboard non risponde — controlla /tmp/dashboard.log"
        fail "Dashboard (porta 7700)"
    fi
fi

# ── STEP 3: Memory server 7701 ───────────────────────────────────────────────
hdr "STEP 3 — Memory server (porta 7701)"
if curl -sf --max-time 3 http://127.0.0.1:7701/health >/dev/null 2>&1; then
    ok "Memory server già attivo"
    pass "Memory server (porta 7701)"
else
    warn "Memory server down — docker start memoria_ai_server..."
    docker start memoria_ai_server 2>/dev/null || true
    sleep 3
    if curl -sf --max-time 3 http://127.0.0.1:7701/health >/dev/null 2>&1; then
        ok "Memory server avviato"
        pass "Memory server (porta 7701)"
    else
        err "Memory server non risponde"
        fail "Memory server (porta 7701)"
    fi
fi

# ── STEP 4: Raspberry Pi ─────────────────────────────────────────────────────
hdr "STEP 4 — Raspberry Pi + porta seriale"
PI_OK=$(python3 -c "
import sys; sys.path.insert(0, '.')
from agent.remote_uploader import is_reachable
print('yes' if is_reachable() else 'no')
" 2>/dev/null)

if [ "$PI_OK" = "yes" ]; then
    ok "Pi raggiungibile (192.168.1.167)"
    pass "Raspberry Pi raggiungibile"

    # Check porta seriale
    SERIAL_CHECK=$(sshpass -p 'pippopippo33$$' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
        lele@192.168.1.167 \
        "ls /dev/ttyUSB0 2>/dev/null && echo PRESENT || echo ABSENT; fuser /dev/ttyUSB0 2>/dev/null && echo BUSY || echo FREE" 2>/dev/null)

    if echo "$SERIAL_CHECK" | grep -q "PRESENT"; then
        ok "ESP32 su /dev/ttyUSB0"
        pass "ESP32 /dev/ttyUSB0 presente"
    else
        err "ESP32 non trovato su /dev/ttyUSB0"
        fail "ESP32 /dev/ttyUSB0 assente"
    fi

    if echo "$SERIAL_CHECK" | grep -q "FREE"; then
        ok "Porta seriale libera"
        pass "Porta seriale libera"
    else
        warn "Porta occupata — kill processi stuck..."
        sshpass -p 'pippopippo33$$' ssh -o StrictHostKeyChecking=no lele@192.168.1.167 \
            "pkill -f esptool; pkill -f 'pio run'; echo done" 2>/dev/null || true
        pass "Porta seriale (processi killati)"
    fi
else
    err "Pi non raggiungibile — prova: sudo ip link set eth0 up && sudo dhcpcd eth0"
    fail "Raspberry Pi non raggiungibile"
    fail "ESP32 /dev/ttyUSB0 (Pi down)"
    fail "Porta seriale (Pi down)"
fi

# ── STEP 5: Webcam ───────────────────────────────────────────────────────────
hdr "STEP 5 — Webcam CSI"
FRAME=$(python3 -c "
import sys; sys.path.insert(0, '.')
from agent.grab import grab_now
r = grab_now(n_frames=1)
print(r['frame_paths'][0] if r.get('ok') and r.get('frame_paths') else 'FAIL')
" 2>/dev/null)

if [ "$FRAME" != "FAIL" ] && [ -n "$FRAME" ]; then
    ok "Frame catturato: $FRAME"
    pass "Webcam CSI"
else
    err "grab_now fallito — webcam non disponibile?"
    fail "Webcam CSI"
fi

# ── STEP 6: Librerie arduino-cli locali ──────────────────────────────────────
hdr "STEP 6 — Librerie arduino-cli (locale)"
LIBS=$(python3 -c "
import sys, json; sys.path.insert(0, '.')
from agent.compiler import check_libraries
r = check_libraries(['Adafruit_SSD1306', 'Adafruit_GFX_Library', 'Adafruit_BusIO'])
print('ok' if r['all_ok'] else 'missing:' + ','.join(r['missing']))
" 2>/dev/null)

if [ "$LIBS" = "ok" ]; then
    ok "Adafruit_SSD1306, Adafruit_GFX_Library, Adafruit_BusIO"
    pass "Librerie arduino-cli"
else
    err "Librerie mancanti: $LIBS"
    fail "Librerie arduino-cli ($LIBS)"
fi

# ── STEP 7: Librerie PlatformIO sul Pi ───────────────────────────────────────
hdr "STEP 7 — Librerie PlatformIO (Raspberry Pi)"
if [ "$PI_OK" = "yes" ]; then
    PIO_LIBS=$(python3 -c "
import sys; sys.path.insert(0, '.')
from agent.remote_uploader import check_pio_libraries
r = check_pio_libraries(['Adafruit SSD1306', 'Adafruit GFX Library'])
print('ok' if r['all_ok'] else 'missing:' + ','.join(r.get('missing',[])))
" 2>/dev/null)

    if [ "$PIO_LIBS" = "ok" ]; then
        ok "Adafruit SSD1306, Adafruit GFX Library"
        pass "Librerie PlatformIO"
    else
        err "Librerie PIO mancanti: $PIO_LIBS"
        fail "Librerie PlatformIO ($PIO_LIBS)"
    fi
else
    warn "Skip PIO check (Pi non raggiungibile)"
    fail "Librerie PlatformIO (Pi down)"
fi

# ── SEMAFORO FINALE ───────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}════════════════════════════════════════${NC}"
echo -e "${BOLD}           PREFLIGHT REPORT             ${NC}"
echo -e "${BOLD}════════════════════════════════════════${NC}"

ALL_OK=true
for line in "${RESULTS[@]}"; do
    echo -e "  $line"
    if echo "$line" | grep -q "❌"; then
        ALL_OK=false
    fi
done

echo -e "${BOLD}════════════════════════════════════════${NC}"
if $ALL_OK; then
    echo -e "\n  ${GREEN}${BOLD}🟢  SISTEMA PRONTO — puoi lanciare il programmatore${NC}\n"
    echo -e "  ${GREEN}python agent/tool_agent.py \"<task>\" --fqbn esp32:esp32:esp32${NC}\n"
else
    echo -e "\n  ${RED}${BOLD}🔴  PREFLIGHT FALLITO — risolvi gli errori sopra${NC}\n"
fi
