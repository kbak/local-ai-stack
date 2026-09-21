#!/usr/bin/env bash
# Qwen-Image 2.1 generation and editing, started on demand by llama-swap.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(dirname "$SCRIPT_DIR")"
PORT="${1:?port arg required}"
MODEL_DIR="${QWEN_IMAGE_MODEL_DIR:-$WORKSPACE/models/image-gen/qwen-image-2.1}"
SD_SERVER="${QWEN_IMAGE_SERVER:-$SCRIPT_DIR/bin/sd-server-qwen-image-2.1}"

export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES="${QWEN_IMAGE_GPU:-0}"

if [[ ! -x "$SD_SERVER" ]]; then
    echo "Missing Qwen image runtime: $SD_SERVER. Run scripts/install-qwen-image-2.1.sh." >&2
    exit 1
fi

for model_file in \
    diffusion_models/qwen_image_2.1_int8_convrot.safetensors \
    text_encoders/Qwen3VL-8B-Instruct-Q4_K_M.gguf \
    text_encoders/mmproj-Qwen3VL-8B-Instruct-F16.gguf \
    vae/qwen_image_2.1_vae_bf16.safetensors; do
    if [[ ! -f "$MODEL_DIR/$model_file" ]]; then
        echo "Missing Qwen image model: $MODEL_DIR/$model_file" >&2
        exit 1
    fi
done

# Limit the image worker's managed GPU allocations so the persistent chat and
# autocomplete models can stay loaded. mmap/auto-fit permit offloading when
# necessary. The GGUF encoder needs a separate vision projector for editing.
exec "$SD_SERVER" \
    --diffusion-model "$MODEL_DIR/diffusion_models/qwen_image_2.1_int8_convrot.safetensors" \
    --llm "$MODEL_DIR/text_encoders/Qwen3VL-8B-Instruct-Q4_K_M.gguf" \
    --llm_vision "$MODEL_DIR/text_encoders/mmproj-Qwen3VL-8B-Instruct-F16.gguf" \
    --vae "$MODEL_DIR/vae/qwen_image_2.1_vae_bf16.safetensors" \
    --listen-ip 127.0.0.2 \
    --listen-port "$PORT" \
    --max-vram "${QWEN_IMAGE_MAX_VRAM:-24}" \
    --mmap \
    --fa \
    --width 1024 --height 1024 \
    --cfg-scale 1.0 \
    --strength 1.0 \
    --steps "${QWEN_IMAGE_STEPS:-40}" \
    --seed -1 \
    --sampling-method euler
