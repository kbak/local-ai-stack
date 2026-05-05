#!/bin/bash
# Launcher for vLLM (Qwen3.6-35B-A3B-FP8), called by llama-swap.
# llama-swap allocates a port and passes it as $1.
# Lives on the host filesystem; copied/run from WSL via wsl.exe.
set -e

PORT="${1:?port arg required}"

cd "$HOME/vllm-runtime"
# shellcheck disable=SC1091
source .venv/bin/activate

export HF_HOME="$HOME/models/hf"
export CUDA_VISIBLE_DEVICES=0
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export TORCHINDUCTOR_COMPILE_THREADS=16

# Stock Qwen3.6-35B-A3B-FP8 (MoE, 3B active) on the primary GPU. Single-user,
# max-num-seqs=1, full 256K context, full FP16 KV. Same xgrammar-via-FP8 path
# as the 27B dense launcher to keep tool-call JSON constrained at decode time.
exec vllm serve Qwen/Qwen3.6-35B-A3B-FP8 \
  --trust-remote-code \
  --served-model-name qwen3.6-35B-A3B-FP8 \
  --port "$PORT" \
  --host 0.0.0.0 \
  --max-model-len 262144 \
  --max-num-seqs 1 \
  --gpu-memory-utilization 0.50 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_xml \
  --override-generation-config '{"repetition_penalty":1.05,"presence_penalty":0.3}' \
  --chat-template "$HOME/vllm-runtime/qwen3.6-librechat.jinja"
