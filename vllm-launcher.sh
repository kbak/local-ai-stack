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

exec vllm serve sakamakismile/Huihui-Qwen3.6-27B-abliterated-NVFP4-MTP \
  --trust-remote-code \
  --quantization modelopt \
  --served-model-name qwen3.6-27B-NVFP4 \
  --port "$PORT" \
  --host 0.0.0.0 \
  --max-model-len 65536 \
  --max-num-seqs 2 \
  --kv-cache-dtype fp8 \
  --gpu-memory-utilization 0.9 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_xml \
  --speculative-config '{"method":"qwen3_5_mtp","num_speculative_tokens":3}' \
  --chat-template "$HOME/vllm-runtime/qwen3.6-librechat.jinja"
