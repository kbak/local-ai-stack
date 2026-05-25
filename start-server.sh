#!/usr/bin/env bash
# Bring up server-side services from docker-compose.server.yml.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set -a
. "$SCRIPT_DIR/.env"
set +a

cd "$SCRIPT_DIR"

echo "Waiting for dockerd socket..."
for i in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 1; done

if grep -qi microsoft /proc/version 2>/dev/null && [ -x /usr/local/sbin/wsl-host-forward ]; then
    echo "Running wsl-host-forward..."
    sudo /usr/local/sbin/wsl-host-forward || echo "(wsl-host-forward failed; container->host routing may be degraded)"
fi

echo "Starting Docker services (server)..."
docker compose -f "$SCRIPT_DIR/docker-compose.server.yml" up -d --wait

echo "Waiting for voice-agent..."
until curl -sf http://localhost:8087/health >/dev/null 2>&1; do
    sleep 2
done

echo "Waiting for memory-mcp..."
until curl -sf http://localhost:8089/health >/dev/null 2>&1; do
    sleep 2
done

echo "Server stack is up."
