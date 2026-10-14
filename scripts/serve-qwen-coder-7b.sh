#!/bin/bash
# Launcher for vLLM (Qwen2.5-Coder-7B base), called by llama-swap.
# FIM/autocomplete backend for VS Code tab-complete on the primary GPU.
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="$(dirname "$REPO_ROOT")"

PORT="${1:?port arg required}"

cd "$WORKSPACE/vllm-runtime"
# shellcheck disable=SC1091
source .venv/bin/activate

export HF_HOME="$WORKSPACE/models/hf"
export CUDA_VISIBLE_DEVICES="${PRIMARY_GPU:-0}"
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export TORCHINDUCTOR_COMPILE_THREADS=16
# vLLM's unauthenticated EngineCore communication sockets must stay local.
export VLLM_HOST_IP=127.0.0.1
# vLLM 0.27 enables its V2 model runner for Qwen2 by default. V2 requires
# CUDA Unified Virtual Addressing, which is unavailable on this WSL GPU path.
export VLLM_USE_V2_MODEL_RUNNER=0

# Use the completion checkpoint with raw FIM prompts, not chat messages.
# Reserve 1 GiB of KV cache explicitly: enough for two 8K sequences. Automatic
# memory profiling can miscount allocations from other resident GPU workers.
exec vllm serve Qwen/Qwen2.5-Coder-7B \
  --revision 0396a76181e127dfc13e5c5ec48a8cee09938b02 \
  --trust-remote-code \
  --served-model-name qwen-coder-7B \
  --port "$PORT" \
  --host 127.0.0.2 \
  --max-model-len 8192 \
  --max-num-seqs 2 \
  --gpu-memory-utilization 0.17 \
  --kv-cache-memory-bytes 1073741824 \
  --dtype bfloat16
