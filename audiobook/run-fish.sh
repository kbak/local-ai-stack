#!/usr/bin/env bash
set -euo pipefail
STACK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export HF_HOME="$STACK_ROOT/.maintenance/audiobook/hf-cache"
export TORCHINDUCTOR_CACHE_DIR="$STACK_ROOT/.maintenance/audiobook/fish-torch-cache"
export TRITON_CACHE_DIR="$STACK_ROOT/.maintenance/audiobook/triton-cache"
export NUMBA_CACHE_DIR="$STACK_ROOT/.maintenance/audiobook/numba-cache"
export XDG_CACHE_HOME="$STACK_ROOT/.maintenance/audiobook/cache"
export MPLCONFIGDIR="$STACK_ROOT/.maintenance/audiobook/mpl-cache"
export OMP_NUM_THREADS=4
exec 9>"$STACK_ROOT/.maintenance/audiobook/inference.lock"
flock -n 9 || { echo 'Another audiobook inference worker is already running.' >&2; exit 1; }
exec "$STACK_ROOT/.maintenance/audiobook/fish-venv/bin/python" -u "$STACK_ROOT/audiobook/fish_render.py" "$@"
