#!/usr/bin/env bash
# Dev helper: rebuild image-gen / image-gen-ui after a Dockerfile change
# and bring them up in the foreground so you can watch SwarmUI's logs.
# Ctrl+C stops both cleanly. The containers are normally always-on (started
# by start.sh) — this script is only useful when you've edited a Dockerfile
# or want to tail logs interactively.
#
# Open http://localhost:7802 to use the UI. Load/unload the model via the
# button in the UI header.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Rebuilding + starting image-gen + image-gen-ui in foreground (Ctrl+C to stop)..."
echo "UI: http://localhost:7802 (engine API: http://localhost:7801)"
echo

# --build rebuilds only if Dockerfiles or build context changed (layer cache
# makes no-op rebuilds ~1s). Naming services explicitly so other always-on
# services aren't restarted.
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up --build image-gen image-gen-ui
