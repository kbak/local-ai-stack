#!/usr/bin/env bash
set -euo pipefail
STACK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export HF_HOME="$STACK_ROOT/.maintenance/audiobook/hf-cache"
export TORCHINDUCTOR_CACHE_DIR="$STACK_ROOT/.maintenance/audiobook/torch-cache"
export TRITON_CACHE_DIR="$STACK_ROOT/.maintenance/audiobook/triton-cache"
export NUMBA_CACHE_DIR="$STACK_ROOT/.maintenance/audiobook/numba-cache"
export XDG_CACHE_HOME="$STACK_ROOT/.maintenance/audiobook/cache"
export OMP_NUM_THREADS=4
if [[ "${1:-}" == voice || "${1:-}" == render ]]; then
  exec 9>"$STACK_ROOT/.maintenance/audiobook/inference.lock"
  flock -n 9 || { echo 'Another audiobook inference worker is already running.' >&2; exit 1; }
fi
exec "$STACK_ROOT/.maintenance/audiobook/venv/bin/python" -u "$STACK_ROOT/scripts/audiobook/audiobook.py" "$@"
