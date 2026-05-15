#!/bin/bash
# Launcher for stable-diffusion.cpp (sd-server), called by llama-swap.
# Serves FLUX.1-dev FP8 image generation via /v1/images/generations on the primary GPU.
#
# Prerequisite: sd-server binary must be in PATH. Build from source at
# https://github.com/leejet/stable-diffusion.cpp (enable CUDA: cmake -DSD_CUBLAS=on).
set -e

PORT="${1:?port arg required}"

export CUDA_VISIBLE_DEVICES=0
export CUDA_DEVICE_ORDER=PCI_BUS_ID

SD_MODELS=/home/kacper/models/image-gen

exec sd-server \
  --diffusion-model "${SD_MODELS}/diffusion_models/flux1-dev-fp8.safetensors" \
  --vae             "${SD_MODELS}/VAE/ae.safetensors" \
  --clip_l          "${SD_MODELS}/text_encoders/clip_l.safetensors" \
  --t5xxl           "${SD_MODELS}/text_encoders/t5xxl_fp8_e4m3fn.safetensors" \
  --listen-ip 0.0.0.0 \
  --listen-port "$PORT" \
  --cfg-scale 1.0 \
  --guidance 3.5 \
  --steps 24 \
  --sampling-method euler \
  --scheduler simple \
  --fa \
  -v
