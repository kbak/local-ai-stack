#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

set -a
# shellcheck disable=SC1091
source "$REPO_ROOT/public-api.env"
set +a

exec "$REPO_ROOT/public-api-gateway/.venv/bin/python" \
  "$REPO_ROOT/public-api-gateway/validate.py"
