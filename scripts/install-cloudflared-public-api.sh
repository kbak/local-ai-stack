#!/usr/bin/env bash
set -euo pipefail

CLOUDFLARED_VERSION="2026.8.3"
CLOUDFLARED_SHA256="f29324fe934d1e100617484c78deef803c4dc2cd351d645bbde42e96b4fccc5e"
CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-amd64"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

curl --fail --show-error --silent --location \
  --output "$tmp_dir/cloudflared" \
  "$CLOUDFLARED_URL"

printf '%s  %s\n' "$CLOUDFLARED_SHA256" "$tmp_dir/cloudflared" \
  | sha256sum --check --status

install -d -m 0755 "$REPO_ROOT/bin"
install -m 0755 "$tmp_dir/cloudflared" "$REPO_ROOT/bin/cloudflared"
printf 'Installed cloudflared %s with verified SHA-256.\n' "$CLOUDFLARED_VERSION"
