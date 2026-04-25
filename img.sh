#!/usr/bin/env bash
# On-demand image generation. Brings up the SwarmUI container in the
# foreground; Ctrl+C stops it cleanly. Expects the primary GPU (5090) to be
# free of the main llama-swap chat model — manually unload it first via:
#   curl -s http://localhost:8080/unload
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WSL_SCRIPT_DIR="$(echo "$SCRIPT_DIR" | sed 's|^/\([a-z]\)/|/mnt/\1/|')"

DOCKER="wsl.exe -d Ubuntu-24.04 -- docker"
COMPOSE_FILE="$WSL_SCRIPT_DIR/docker-compose.yml"

cleanup() {
    echo
    echo "Stopping image-gen..."
    MSYS_NO_PATHCONV=1 $DOCKER compose -f "$COMPOSE_FILE" --profile image stop image-gen >/dev/null 2>&1 || true
    echo "VRAM after shutdown:"
    wsl.exe -d Ubuntu-24.04 -- nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader,nounits
}
trap cleanup EXIT

echo "VRAM before launch:"
wsl.exe -d Ubuntu-24.04 -- nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader,nounits
echo

# Warn if a main-group llama-swap model is currently loaded
RUNNING_JSON="$(curl -sf http://localhost:8080/running 2>/dev/null || echo '{"running":[]}')"
MAIN_LOADED="$(echo "$RUNNING_JSON" | python -c "
import json, sys
data = json.load(sys.stdin)
# Heuristic: anything with --device CUDA0 and no CUDA_VISIBLE_DEVICES override
# in cmd is on the primary GPU. cuda1 group entries have CUDA_VISIBLE_DEVICES
# in their env but that's not in /running output, so fall back to model name
# matching the known small-model patterns instead.
SECONDARY_PATTERNS = ('coder', 'qwen3.5-9B')
main = [m for m in data.get('running', [])
        if not any(p.lower() in m.get('model', '').lower() for p in SECONDARY_PATTERNS)]
if main:
    print(','.join(m['model'] for m in main))
" 2>/dev/null || echo "")"

if [ -n "$MAIN_LOADED" ]; then
    echo "WARNING: main-group model(s) currently loaded on primary GPU:"
    echo "    $MAIN_LOADED"
    echo
    echo "Image-gen needs ~28 GB on the primary GPU. Unload first:"
    echo "    curl -s http://localhost:8080/unload"
    echo
    read -r -p "Continue anyway? [y/N] " ans
    case "$ans" in
        [yY]|[yY][eE][sS]) ;;
        *) exit 1 ;;
    esac
fi

echo "Starting image-gen (Ctrl+C to stop)..."
echo "UI will be at http://localhost:7801 once 'Program is running' appears."
echo

MSYS_NO_PATHCONV=1 $DOCKER compose -f "$COMPOSE_FILE" --profile image up image-gen
