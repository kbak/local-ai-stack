#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$REPO_ROOT/.env" ]] && { set -a; source "$REPO_ROOT/.env"; set +a; }

: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN must be set}"
: "${CLOUDFLARE_ZONE_ID:?CLOUDFLARE_ZONE_ID must be set}"

MY_IP="$(tailscale ip -4 2>/dev/null)"
: "${MY_IP:?Could not detect Tailscale IP — is tailscale running?}"

DOMAIN="kacper.me"
CF_API="https://api.cloudflare.com/client/v4"
# memory.kacper.me lives on the AI box now (memory-mcp moved to docker-compose.ai.yml).
SERVER_HOSTS=(voice chat search pdf mcp nextcloud)

cf() { curl -sSf -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" "$@"; }

update() {
  local fqdn="${1}.${DOMAIN}"
  local rec
  rec=$(cf "${CF_API}/zones/${CLOUDFLARE_ZONE_ID}/dns_records?name=${fqdn}&type=A")
  local id cur
  id=$(jq -r '.result[0].id' <<< "$rec")
  cur=$(jq -r '.result[0].content' <<< "$rec")

  [[ "$id" == "null" ]] && { echo "  SKIP  $fqdn — no record"; return; }
  [[ "$cur" == "$MY_IP" ]] && { echo "  OK    $fqdn → $MY_IP"; return; }

  cf -X PUT -H "Content-Type: application/json" \
    --data "{\"type\":\"A\",\"name\":\"${fqdn}\",\"content\":\"${MY_IP}\",\"proxied\":false,\"ttl\":60}" \
    "${CF_API}/zones/${CLOUDFLARE_ZONE_ID}/dns_records/${id}" \
    | jq -r '"  UPDATE " + .result.name + " → " + .result.content'
}

echo "Syncing server DNS records → ${MY_IP}"
for h in "${SERVER_HOSTS[@]}"; do update "$h"; done
echo "Done. Records propagate within ~60 s."
