#!/bin/bash
# Launcher for vLLM, called by llama-swap.
# llama-swap allocates a port and passes it as $1.
# Activates the vLLM venv at ~/vllm-runtime/.venv and execs `vllm serve`.
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

# Stock Qwen3.8-27B-FP8 on the primary GPU. The model natively supports 262K,
# but this single-user profile caps it at 128K to preserve VRAM headroom for
# the persistent coder model. Use the checkpoint's bundled chat template so
# reasoning_effort and preserve_thinking remain available to API clients.
exec vllm serve Qwen/Qwen3.8-27B-FP8 \
  --trust-remote-code \
  --served-model-name qwen3.8-27B-FP8 \
  --port "$PORT" \
  --host 0.0.0.0 \
  --max-model-len 131072 \
  --max-num-seqs 2 \
  --gpu-memory-utilization 0.45 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder
