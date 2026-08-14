#!/bin/bash
# Launcher for vLLM (Qwen2.5-Coder-7B-Instruct), called by llama-swap.
# FIM/autocomplete backend for VS Code tab-complete on the primary GPU.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(dirname "$SCRIPT_DIR")"

PORT="${1:?port arg required}"

cd "$WORKSPACE/vllm-runtime"
# shellcheck disable=SC1091
source .venv/bin/activate

export HF_HOME="$WORKSPACE/models/hf"
export CUDA_VISIBLE_DEVICES=0
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export TORCHINDUCTOR_COMPILE_THREADS=16
# vLLM 0.27 enables its V2 model runner for Qwen2 by default. V2 requires
# CUDA Unified Virtual Addressing, which is unavailable on this WSL GPU path.
export VLLM_USE_V2_MODEL_RUNNER=0

exec vllm serve Qwen/Qwen2.5-Coder-7B-Instruct \
  --trust-remote-code \
  --served-model-name qwen-coder-7B \
  --port "$PORT" \
  --host 0.0.0.0 \
  --max-model-len 8192 \
  --max-num-seqs 2 \
  --gpu-memory-utilization 0.17 \
  --dtype bfloat16
