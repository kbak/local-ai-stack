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

# Stock Qwen3.6-27B-FP8 -- the only quant still on disk after the
# 2026-05-01 cleanup (community NVFP4/AWQ variants deleted as dead-ends).
# This DOES NOT FIT on 32 GB Blackwell: vLLM OOMs at graph capture, SGLang
# OOMs during weight copy. Kept ready-to-run for the VRAM-upgrade scenario
# (Pro 6000 / 4090 48GB / RTX 6000 Ada). On 48+ GB you can safely raise
# --max-model-len back up and re-enable speculative-config.
exec vllm serve Qwen/Qwen3.6-27B-FP8 \
  --trust-remote-code \
  --served-model-name qwen3.6-27B-FP8 \
  --port "$PORT" \
  --host 0.0.0.0 \
  --max-model-len 16384 \
  --max-num-seqs 2 \
  --kv-cache-dtype fp8 \
  --gpu-memory-utilization 0.92 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_xml \
  --chat-template "$HOME/vllm-runtime/qwen3.6-librechat.jinja"
