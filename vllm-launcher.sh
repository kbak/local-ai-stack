#!/bin/bash
# Launcher for vLLM, called by llama-swap.
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

# Stock Qwen3.6-27B-FP8 on the primary GPU. Single-user, max-num-seqs=1,
# 128K context, full FP16 KV. Resolves the LibreChat agent spiral
# pathology documented in project_vllm_qwen36_spiral.md: FP8 stock weights
# + the default `--structured-outputs-config.backend=auto` (which picks
# xgrammar on FP8) constrain tool-call JSON at decode time and prevent the
# synonym/word-list collapse seen on community AWQ/NVFP4 quants.
exec vllm serve Qwen/Qwen3.6-27B-FP8 \
  --trust-remote-code \
  --served-model-name qwen3.6-27B-FP8 \
  --port "$PORT" \
  --host 0.0.0.0 \
  --max-model-len 131072 \
  --max-num-seqs 2 \
  --gpu-memory-utilization 0.40 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_xml \
  --override-generation-config '{"repetition_penalty":1.05,"presence_penalty":0.3}' \
  --chat-template "$HOME/vllm-runtime/qwen3.6-librechat.jinja"
