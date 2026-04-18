#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Starting llama-swap..."
llama-swap --config "$SCRIPT_DIR/llama-swap.yaml" >/dev/null 2>&1 &

echo "Pre-loading default model (qwen) before Docker stack..."
until curl -sf http://localhost:8080/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"qwen","messages":[{"role":"user","content":"hi"}],"max_tokens":1}' \
    >/dev/null 2>&1; do
    sleep 2
done

echo "Starting yt-dlp service..."
cd "$SCRIPT_DIR/yt-dlp-service"
python server.py >/dev/null 2>&1 &
cd "$SCRIPT_DIR"

echo "Starting Docker services..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d --build

echo "Waiting for all containers to be up..."
until docker compose -f "$SCRIPT_DIR/docker-compose.yml" ps --format json \
    | python -c "
import sys, json
states = [json.loads(l)['State'] for l in sys.stdin if l.strip()]
all_up = all(s == 'running' for s in states)
sys.exit(0 if all_up else 1)
" 2>/dev/null; do
    sleep 2
done

echo "Stack is up. (signal-bot will warm up Whisper + Kokoro in background)"
