#!/bin/bash
# Launcher for vLLM (Qwen2.5-Coder-7B-Instruct), called by llama-swap.
# FIM/autocomplete backend for VS Code tab-complete on the primary GPU.
set -e

PORT="${1:?port arg required}"

cd "$HOME/vllm-runtime"
# shellcheck disable=SC1091
source .venv/bin/activate

export HF_HOME="$HOME/models/hf"
export CUDA_VISIBLE_DEVICES=0
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export TORCHINDUCTOR_COMPILE_THREADS=16

exec vllm serve Qwen/Qwen2.5-Coder-7B-Instruct \
  --trust-remote-code \
  --served-model-name qwen-coder-7B \
  --port "$PORT" \
  --host 0.0.0.0 \
  --max-model-len 8192 \
  --max-num-seqs 2 \
  --gpu-memory-utilization 0.17 \
  --dtype bfloat16
