#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
PUBLIC_ENV="$REPO_ROOT/public-api.env"
TUNNEL_ENV="$REPO_ROOT/cloudflared.env"

umask 077

if [[ ! -e "$PUBLIC_ENV" ]]; then
  api_key="$(openssl rand -hex 32)"
  {
    printf 'PUBLIC_API_BEARER_KEY=%s\n' "$api_key"
    printf 'PUBLIC_API_MODELS=qwen3.8-27B-FP8,qwen3.6-35B-A3B-FP8\n'
    printf 'PUBLIC_API_UPSTREAM=http://[::1]:8080\n'
    printf 'PUBLIC_API_MAX_BODY_BYTES=10485760\n'
  } >"$PUBLIC_ENV"
  unset api_key
  printf 'Created %s with a random bearer key.\n' "$PUBLIC_ENV"
else
  printf 'Preserved existing %s.\n' "$PUBLIC_ENV"
fi

if [[ ! -e "$TUNNEL_ENV" ]]; then
  {
    printf 'TUNNEL_TOKEN=\n'
    printf 'TUNNEL_METRICS=127.0.0.1:20001\n'
    printf 'TUNNEL_LOGLEVEL=info\n'
  } >"$TUNNEL_ENV"
  printf 'Created %s with an empty tunnel-token placeholder.\n' "$TUNNEL_ENV"
else
  printf 'Preserved existing %s.\n' "$TUNNEL_ENV"
fi

chmod 600 "$PUBLIC_ENV" "$TUNNEL_ENV"
