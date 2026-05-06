#!/bin/bash
# Launcher for vLLM (Qwen2.5-Coder-1.5B-Instruct, FP16), called by llama-swap.
# Used as the FIM/autocomplete backend for VS Code tab-complete.
#
# Pinned to the secondary GPU (5060 Ti) so it doesn't contend with the main
# chat model on the primary GPU. ~3 GB weights + KV cache headroom; util
# fraction kept low because the 5060 Ti also hosts audio-api workloads.
#
# Always-loaded (cuda1 group has persistent: true), so cold start cost is
# paid once on stack startup and never during editor use.
set -e

PORT="${1:?port arg required}"

cd "$HOME/vllm-runtime"
# shellcheck disable=SC1091
source .venv/bin/activate

export HF_HOME="$HOME/models/hf"
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export TORCHINDUCTOR_COMPILE_THREADS=16

# llama-swap injects CUDA_VISIBLE_DEVICES=$SECONDARY_GPU as a UUID for slot-
# stable GPU pinning. vLLM 0.20.1 calls int(CUDA_VISIBLE_DEVICES) and chokes
# on UUIDs, so resolve to a numeric index here.
if [[ "${CUDA_VISIBLE_DEVICES:-}" == GPU-* ]]; then
    IDX=$(nvidia-smi --query-gpu=index,uuid --format=csv,noheader \
          | awk -F', ' -v uuid="$CUDA_VISIBLE_DEVICES" '$2==uuid {print $1; exit}')
    if [[ -z "$IDX" ]]; then
        echo "ERROR: GPU UUID $CUDA_VISIBLE_DEVICES not found by nvidia-smi" >&2
        exit 1
    fi
    export CUDA_VISIBLE_DEVICES="$IDX"
fi

exec vllm serve Qwen/Qwen2.5-Coder-1.5B-Instruct \
  --trust-remote-code \
  --served-model-name qwen-coder-1.5B \
  --port "$PORT" \
  --host 0.0.0.0 \
  --max-model-len 8192 \
  --max-num-seqs 1 \
  --gpu-memory-utilization 0.40 \
  --dtype float16
