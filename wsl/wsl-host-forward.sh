#!/usr/bin/env bash
# Forwards Docker container traffic destined for docker0 (172.17.0.1)
# to the WSL2 VM's gateway (the Windows host). Enables containers to
# reach Windows services via host.docker.internal on any port without
# per-service config. Idempotent; safe to re-run.
set -euo pipefail

WIN_GW="$(ip route show default | awk '/default/ {print $3; exit}')"
if [[ -z "$WIN_GW" ]]; then
    echo "Could not determine Windows gateway" >&2
    exit 1
fi

iptables -t nat -N DOCKER-HOST-FWD 2>/dev/null || true
iptables -t nat -F DOCKER-HOST-FWD
iptables -t nat -C PREROUTING -d 172.17.0.1 -j DOCKER-HOST-FWD 2>/dev/null \
    || iptables -t nat -A PREROUTING -d 172.17.0.1 -j DOCKER-HOST-FWD
iptables -t nat -A DOCKER-HOST-FWD -p tcp -j DNAT --to-destination "$WIN_GW"
iptables -t nat -A DOCKER-HOST-FWD -p udp -j DNAT --to-destination "$WIN_GW"

echo "Forwarding 172.17.0.1 -> $WIN_GW"
