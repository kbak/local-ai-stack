#!/bin/bash
# Launcher for Muse Glimmer's dedicated vLLM image, called by llama-swap.
# Keeping this runtime in Docker avoids changing the working local vLLM venv.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(dirname "$SCRIPT_DIR")"

PORT="${1:?port arg required}"
CONTAINER_NAME="llama-swap-muse-glimmer-${PORT}"

cleanup() {
  docker stop --time 30 "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# The dedicated image contains the pre-release Muse Glimmer architecture,
# reasoning parser, and tool-call parser. The HF cache is shared with the
# local vLLM launchers so model files survive container replacement.
docker run --rm \
  --name "$CONTAINER_NAME" \
  --gpus device=0 \
  --ipc=host \
  --network=host \
  -e HF_HOME=/root/.cache/huggingface \
  -e CUDA_DEVICE_ORDER=PCI_BUS_ID \
  -e VLLM_USE_V2_MODEL_RUNNER=0 \
  -e VLLM_HOST_IP=127.0.0.1 \
  -v "$WORKSPACE/models/hf:/root/.cache/huggingface" \
  -v "$WORKSPACE/models/vllm-muse-cache:/root/.cache/vllm" \
  vllm/vllm-openai:muse-glimmer@sha256:3dd2f182bdfccde57a67b91d79a563f37c870bd3c08dc8033532e4232737519a \
  RedHatAI/Muse-Glimmer-30B-FP8-block \
  --served-model-name muse-glimmer-30B-FP8 \
  --port "$PORT" \
  --host 127.0.0.2 \
  --generation-config auto \
  --tensor-parallel-size 1 \
  --max-model-len 131072 \
  --max-num-seqs 2 \
  --gpu-memory-utilization 0.45 \
  --limit-mm-per-prompt '{"image":0,"video":0}' \
  --enable-auto-tool-choice \
  --tool-call-parser muse_glimmer \
  --reasoning-parser muse_glimmer
