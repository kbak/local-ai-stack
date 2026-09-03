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
# vLLM's unauthenticated EngineCore communication sockets must stay local.
export VLLM_HOST_IP=127.0.0.1

# Pin to the secondary GPU. Prefer an inherited value, but fall back to the
# project .env so restarting llama-swap from a non-interactive shell does not
# silently drop the GPU selection.
if [[ -z "${SECONDARY_GPU:-}" && -f "$SCRIPT_DIR/.env" ]]; then
    SECONDARY_GPU=$(sed -n 's/^SECONDARY_GPU=//p' "$SCRIPT_DIR/.env" | tail -n 1)
    SECONDARY_GPU="${SECONDARY_GPU%$'\r'}"
    SECONDARY_GPU="${SECONDARY_GPU#\"}"
    SECONDARY_GPU="${SECONDARY_GPU%\"}"
fi
export CUDA_VISIBLE_DEVICES="${SECONDARY_GPU:?SECONDARY_GPU must be set in the environment or project .env}"

# vLLM rejects GPU UUID strings; resolve to numeric index.
if [[ "${CUDA_VISIBLE_DEVICES:-}" == GPU-* ]]; then
    NVIDIA_SMI="${NVIDIA_SMI:-/usr/lib/wsl/lib/nvidia-smi}"
    [[ -x "$NVIDIA_SMI" ]] || { echo "ERROR: nvidia-smi not found at $NVIDIA_SMI" >&2; exit 1; }
    IDX=$("$NVIDIA_SMI" --query-gpu=index,uuid --format=csv,noheader \
          | awk -F', ' -v uuid="$CUDA_VISIBLE_DEVICES" '$2==uuid {print $1; exit}')
    [[ -z "$IDX" ]] && { echo "ERROR: GPU UUID $CUDA_VISIBLE_DEVICES not found" >&2; exit 1; }
    export CUDA_VISIBLE_DEVICES="$IDX"
fi

exec vllm serve BAAI/bge-reranker-v2-m3 \
  --served-model-name bge-reranker-v2-m3 \
  --runner pooling \
  --port "$PORT" \
  --host 127.0.0.2 \
  --gpu-memory-utilization 0.10 \
  --dtype float16
