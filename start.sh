#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Export .env so llama-swap and its serve-*.sh subprocesses inherit all vars
# (SECONDARY_GPU in particular — serve-reranker.sh reads it directly).
# docker-compose reads .env on its own; llama-swap only sees what we export.
set -a
. "$SCRIPT_DIR/.env"
set +a

cd "$SCRIPT_DIR"
echo "Starting llama-swap..."
nohup llama-swap --config llama-swap.yaml >/tmp/llama-swap.log 2>&1 &
disown

echo "Pre-loading qwen-coder-7B (cuda0_coder, persistent)..."
until curl -sf http://localhost:8080/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"qwen-coder-7B","messages":[{"role":"user","content":"hi"}],"max_tokens":1}' \
    >/dev/null 2>&1; do
    sleep 2
done

echo "Pre-loading bge-reranker-v2-m3 (cuda1_reranker, persistent)..."
until curl -sf http://localhost:8080/v1/score \
    -H "Content-Type: application/json" \
    -d '{"model":"bge-reranker-v2-m3","text_1":"test","text_2":["test"]}' \
    >/dev/null 2>&1; do
    sleep 2
done

echo "Pre-loading 35B chat model (cuda0_main, persistent)..."
until curl -sf http://localhost:8080/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"qwen3.6-35B-A3B-FP8","messages":[{"role":"user","content":"hi"}],"max_tokens":1}' \
    >/dev/null 2>&1; do
    sleep 2
done

echo "Starting yt-dlp service..."
cd "$SCRIPT_DIR/yt-dlp-service"
nohup "$HOME/yt-dlp-service-venv/bin/python" server.py >/tmp/yt-dlp-service.log 2>&1 &
disown
cd "$SCRIPT_DIR"

echo "Waiting for dockerd socket..."
for i in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 1; done
if grep -qi microsoft /proc/version 2>/dev/null; then
    echo "Running wsl-host-forward..."
    sudo /usr/local/sbin/wsl-host-forward || echo "(wsl-host-forward failed; container->host routing may be degraded)"
fi
echo "Starting Docker services..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d

echo "Waiting for all containers to be up..."
until docker compose -f "$SCRIPT_DIR/docker-compose.yml" ps --format json \
    | python3 -c "
import sys, json
states = [json.loads(l)['State'] for l in sys.stdin if l.strip()]
all_up = all(s == 'running' for s in states)
sys.exit(0 if all_up else 1)
" 2>/dev/null; do
    sleep 2
done

echo "Waiting for audio-api to load Whisper + Kokoro + Chatterbox..."
until docker logs audio-api 2>&1 | grep -q "Chatterbox warmup complete"; do
    sleep 3
done

echo "Waiting for voice-agent..."
until curl -sf http://localhost:8087/health >/dev/null 2>&1; do
    sleep 2
done

echo "Waiting for memory-mcp (bge-m3 + Mem0)..."
until curl -sf http://localhost:8089/health >/dev/null 2>&1; do
    sleep 2
done

echo "Stack is up."
