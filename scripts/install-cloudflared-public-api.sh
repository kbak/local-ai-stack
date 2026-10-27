#!/usr/bin/env bash
set -euo pipefail

CLOUDFLARED_VERSION="2026.10.4"
CLOUDFLARED_SHA256="ae5e8add7884b0531d66bbca4570d1de491ff6da51e4ebe7eb160cdf241d9e42"
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
