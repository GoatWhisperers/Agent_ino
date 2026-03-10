#!/bin/bash
# Avvia il container MI50 server (Qwen3.5-9B)
# Uso: bash docker/run_mi50.sh [--build]
#
# --build  forza il rebuild dell'immagine prima di avviare

set -e

IMAGE="mi50-server"
PORT=11434
CONTAINER_NAME="mi50-server"

# Rebuild opzionale
if [[ "$1" == "--build" ]]; then
    echo "[MI50 Docker] Building image..."
    cd "$(dirname "$0")/.."
    docker build -f docker/Dockerfile.mi50 -t "$IMAGE" .
    echo "[MI50 Docker] Build completato."
fi

# Ferma container esistente (se presente)
if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
    echo "[MI50 Docker] Container già attivo — niente da fare."
    exit 0
fi
if docker ps -aq -f name="$CONTAINER_NAME" | grep -q .; then
    echo "[MI50 Docker] Rimuovo container fermo..."
    docker rm "$CONTAINER_NAME"
fi

# Health check: se la porta risponde già, non avviare
if curl -sf http://localhost:$PORT/health > /dev/null 2>&1; then
    echo "[MI50 Docker] Server già healthy su porta $PORT — skip."
    exit 0
fi

echo "[MI50 Docker] Avvio container $CONTAINER_NAME..."
AGENT_DIR="$(cd "$(dirname "$0")/.." && pwd)/agent"
docker run -d \
    --name "$CONTAINER_NAME" \
    --device /dev/kfd \
    --device /dev/dri \
    --group-add video \
    --group-add render \
    -v /mnt/raid0:/mnt/raid0:ro \
    -v "$AGENT_DIR/mi50_server.py":/app/mi50_server.py:ro \
    -p $PORT:$PORT \
    "$IMAGE"

# Attendi health
echo "[MI50 Docker] Attendo che il server sia healthy..."
for i in $(seq 1 60); do
    if curl -sf http://localhost:$PORT/health > /dev/null 2>&1; then
        echo "[MI50 Docker] ✅ Server healthy! (${i}s)"
        exit 0
    fi
    sleep 5
done

echo "[MI50 Docker] ❌ Timeout — server non ha risposto in 5 minuti"
docker logs --tail 30 "$CONTAINER_NAME"
exit 1
