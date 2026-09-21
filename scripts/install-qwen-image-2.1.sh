#!/usr/bin/env bash
# Install the pinned image runtime and quantized model without replacing FLUX.
set -euo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="$(dirname "$STACK_DIR")"
SOURCE_REV=c678dfe704a2230342376b46add9c8ca736a653d
MODEL_REV=ace0edeb3791a594ddfa36ed5f41a178a394e921
ENCODER_REV=f982a07559d4a2f6c8744d840bf6fccab30eea96
SOURCE_DIR="${QWEN_IMAGE_BUILD_DIR:-$WORKSPACE/runtimes/sdcpp-$SOURCE_REV}"
MODEL_DIR="${QWEN_IMAGE_MODEL_DIR:-$WORKSPACE/models/image-gen/qwen-image-2.1}"
RGBA_PATCH="$STACK_DIR/patches/sdcpp-qwen-image-rgba.patch"

for dependency in git cmake hf; do
    command -v "$dependency" >/dev/null || { echo "Missing dependency: $dependency" >&2; exit 1; }
done

if [[ ! -d "$SOURCE_DIR/.git" ]]; then
    git clone --no-checkout https://github.com/leejet/stable-diffusion.cpp.git "$SOURCE_DIR"
elif [[ -n "$(git -C "$SOURCE_DIR" status --porcelain --untracked-files=no)" ]]; then
    # Re-running our installer is safe; reject any other source modifications.
    if [[ "$(git -C "$SOURCE_DIR" rev-parse HEAD)" != "$SOURCE_REV" ]] || \
        ! git -C "$SOURCE_DIR" diff HEAD --binary | cmp -s - "$RGBA_PATCH"; then
        echo "Refusing to change a modified runtime checkout: $SOURCE_DIR" >&2
        exit 1
    fi
    git -C "$SOURCE_DIR" apply --reverse "$RGBA_PATCH"
fi
git -C "$SOURCE_DIR" checkout --detach "$SOURCE_REV"
git -C "$SOURCE_DIR" submodule update --init --recursive
git -C "$SOURCE_DIR" apply "$RGBA_PATCH"

# Blackwell workstation GPU. Override the architecture when using another GPU.
cmake -S "$SOURCE_DIR" -B "$SOURCE_DIR/build" \
    -DCMAKE_BUILD_TYPE=Release -DSD_CUDA=ON \
    -DCMAKE_CUDA_ARCHITECTURES="${QWEN_IMAGE_CUDA_ARCH:-120}" \
    -DSD_SERVER_BUILD_FRONTEND=OFF -DSD_WEBM=OFF -DSD_WEBP=OFF
cmake --build "$SOURCE_DIR/build" --target sd-server -j "${QWEN_IMAGE_BUILD_JOBS:-3}"

hf download Comfy-Org/Qwen-Image-2.1 \
    diffusion_models/qwen_image_2.1_int8_convrot.safetensors \
    vae/qwen_image_2.1_vae_bf16.safetensors \
    --revision "$MODEL_REV" --local-dir "$MODEL_DIR"
hf download Qwen/Qwen3-VL-8B-Instruct-GGUF \
    Qwen3VL-8B-Instruct-Q4_K_M.gguf mmproj-Qwen3VL-8B-Instruct-F16.gguf \
    --revision "$ENCODER_REV" --local-dir "$MODEL_DIR/text_encoders"

mkdir -p "$STACK_DIR/bin"
install -m 755 "$SOURCE_DIR/build/bin/sd-server" "$STACK_DIR/bin/sd-server-qwen-image-2.1.new"
mv "$STACK_DIR/bin/sd-server-qwen-image-2.1.new" "$STACK_DIR/bin/sd-server-qwen-image-2.1"
"$STACK_DIR/bin/sd-server-qwen-image-2.1" --version
echo "Installed Qwen-Image 2.1. See docs/qwen-image-2.1.md for activation and LibreChat setup."
