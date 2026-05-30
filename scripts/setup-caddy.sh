#!/usr/bin/env bash
# Configure system Caddy to serve the stack's hostnames with Cloudflare DNS-01 TLS.
# Run: sudo bash scripts/setup-caddy.sh [acme-email]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
set -a; source "$REPO_ROOT/.env"; set +a

ACME_EMAIL="${1:-${ACME_EMAIL:-spam@kacper.me}}"
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN must be set in .env}"

echo "[1] env file -> /etc/caddy/caddy.env (ACME_EMAIL=$ACME_EMAIL)"
install -d -m 0755 /etc/caddy
umask 077
cat > /etc/caddy/caddy.env <<EOF
ACME_EMAIL=$ACME_EMAIL
CLOUDFLARE_API_TOKEN=$CLOUDFLARE_API_TOKEN
EOF
chmod 600 /etc/caddy/caddy.env

echo "[2] systemd drop-in -> load caddy.env"
install -d -m 0755 /etc/systemd/system/caddy.service.d
cat > /etc/systemd/system/caddy.service.d/override.conf <<'EOF'
[Service]
EnvironmentFile=/etc/caddy/caddy.env
EOF

echo "[3] install Caddyfile"
install -m 0644 "$REPO_ROOT/caddy/Caddyfile.server" /etc/caddy/Caddyfile

echo "[4] check ports 80/443 are free"
ss -tlnp 2>/dev/null | grep -E ':80 |:443 ' && echo "  WARNING: something already on 80/443 (above)" || echo "  80/443 free"

echo "[5] validate config"
caddy validate --config /etc/caddy/Caddyfile --envfile /etc/caddy/caddy.env

echo "[6] reload systemd + restart caddy"
systemctl daemon-reload
systemctl enable --now caddy
systemctl restart caddy
sleep 2
systemctl --no-pager --full status caddy | head -12
