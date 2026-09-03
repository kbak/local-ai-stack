#!/usr/bin/env bash
set -euo pipefail

children=()

stop_children() {
  if ((${#children[@]})); then
    kill "${children[@]}" 2>/dev/null || true
    wait "${children[@]}" 2>/dev/null || true
  fi
}
trap stop_children EXIT INT TERM

# Keep existing IPv4-loopback clients working while llama-swap itself listens
# on IPv6 loopback for the unchanged Windows Caddy [::1]:8080 origin.
socat \
  TCP4-LISTEN:8080,bind=127.0.0.1,reuseaddr,fork \
  'TCP6:[::1]:8080' &
children+=("$!")

# Preserve memory-mcp's existing host.docker.internal:172.18.0.1 route without
# exposing port 8080 on the WSL LAN-facing eth0 interface.
socat \
  TCP4-LISTEN:8080,bind=172.18.0.1,reuseaddr,fork \
  'TCP6:[::1]:8080' &
children+=("$!")

wait -n "${children[@]}"
