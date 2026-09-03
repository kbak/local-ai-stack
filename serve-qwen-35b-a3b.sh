#!/bin/bash
# Launcher for vLLM (Qwen3.6-35B-A3B-FP8), called by llama-swap.
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
# vLLM's unauthenticated EngineCore communication sockets must stay local.
export VLLM_HOST_IP=127.0.0.1
# vLLM 0.27's auto-selected DeepGEMM path cannot transform this checkpoint's
# FP8 MoE scale-factor layout on the RTX Pro 6000. Use the compatible fallback
# MoE backend instead of bypassing DeepGEMM's layout assertion.
export VLLM_MOE_USE_DEEP_GEMM=0

# Stock Qwen3.6-35B-A3B-FP8 (MoE, 3B active) on the primary GPU. Single-user,
# max-num-seqs=1, full 256K context, full FP16 KV. Same xgrammar-via-FP8 path
# as the 27B dense launcher to keep tool-call JSON constrained at decode time.
exec vllm serve Qwen/Qwen3.6-35B-A3B-FP8 \
  --trust-remote-code \
  --served-model-name qwen3.6-35B-A3B-FP8 \
  --port "$PORT" \
  --host 127.0.0.2 \
  --max-model-len 262144 \
  --max-num-seqs 2 \
  --gpu-memory-utilization 0.50 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_xml \
  --override-generation-config '{"repetition_penalty":1.05,"presence_penalty":0.3}' \
  --chat-template "$WORKSPACE/vllm-runtime/qwen3.6-librechat.jinja"
