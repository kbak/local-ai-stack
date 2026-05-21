#!/bin/bash
# Launcher for vLLM reranker (bge-reranker-v2-m3), called by llama-swap.
# Cross-encoder scoring via /v1/score on the secondary GPU (5060 Ti).
# ~1.1 GB weights — persistent alongside audio-api; utilization kept low.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(dirname "$SCRIPT_DIR")"

PORT="${1:?port arg required}"

cd "$WORKSPACE/vllm-runtime"
# shellcheck disable=SC1091
source .venv/bin/activate

export HF_HOME="$WORKSPACE/models/hf"
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export TORCHINDUCTOR_COMPILE_THREADS=16

# Pin to the secondary GPU. llama-swap env: fields are not shell-expanded,
# so we read SECONDARY_GPU directly — it's inherited from llama-swap's env.
export CUDA_VISIBLE_DEVICES="${SECONDARY_GPU:?SECONDARY_GPU must be exported in the llama-swap environment}"

# vLLM rejects GPU UUID strings; resolve to numeric index.
if [[ "${CUDA_VISIBLE_DEVICES:-}" == GPU-* ]]; then
    IDX=$(nvidia-smi --query-gpu=index,uuid --format=csv,noheader \
          | awk -F', ' -v uuid="$CUDA_VISIBLE_DEVICES" '$2==uuid {print $1; exit}')
    [[ -z "$IDX" ]] && { echo "ERROR: GPU UUID $CUDA_VISIBLE_DEVICES not found" >&2; exit 1; }
    export CUDA_VISIBLE_DEVICES="$IDX"
fi

exec vllm serve BAAI/bge-reranker-v2-m3 \
  --served-model-name bge-reranker-v2-m3 \
  --runner pooling \
  --port "$PORT" \
  --host 0.0.0.0 \
  --gpu-memory-utilization 0.10 \
  --dtype float16
