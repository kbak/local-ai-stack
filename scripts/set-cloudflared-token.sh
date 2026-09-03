#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
TUNNEL_ENV="$REPO_ROOT/cloudflared.env"

read -r -s -p "Cloudflare tunnel token: " tunnel_token
printf '\n'

if [[ -z "$tunnel_token" ]]; then
  printf 'Token cannot be empty.\n' >&2
  exit 1
fi
if [[ "$tunnel_token" == *$'\n'* || "$tunnel_token" == *$'\r'* ]]; then
  printf 'Token cannot contain a newline.\n' >&2
  exit 1
fi

umask 077
tmp_file="$(mktemp "$REPO_ROOT/.cloudflared.env.XXXXXX")"
trap 'rm -f "$tmp_file"' EXIT
{
  printf 'TUNNEL_TOKEN=%s\n' "$tunnel_token"
  printf 'TUNNEL_METRICS=127.0.0.1:20001\n'
  printf 'TUNNEL_LOGLEVEL=info\n'
} >"$tmp_file"
unset tunnel_token

mv "$tmp_file" "$TUNNEL_ENV"
trap - EXIT
chmod 600 "$TUNNEL_ENV"
printf 'Stored the tunnel token in ignored mode-0600 cloudflared.env.\n'
