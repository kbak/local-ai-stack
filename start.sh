#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Export .env so llama-swap can resolve ${env.SECONDARY_GPU} in its config.
# docker-compose reads .env on its own, but llama-swap is a host process and
# only sees vars we export here.
set -a
. "$SCRIPT_DIR/.env"
set +a

echo "Starting llama-swap..."
nohup llama-swap --config "$SCRIPT_DIR/llama-swap.yaml" >/tmp/llama-swap.log 2>&1 &
disown

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

echo "Pre-loading qwen-coder-1.5B (cuda1, persistent)..."
until curl -sf http://localhost:8080/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"qwen-coder-1.5B","messages":[{"role":"user","content":"hi"}],"max_tokens":1}' \
    >/dev/null 2>&1; do
    sleep 2
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
