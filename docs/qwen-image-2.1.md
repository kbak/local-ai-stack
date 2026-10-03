# Image generation and editing

Qwen-Image 2.1 runs through stable-diffusion.cpp and llama-swap. It shares the
`cuda0_image` group with FLUX: one image worker runs at a time, with a ten-minute
idle timeout. `start-ai.sh` preloads Qwen-Image.

## Install

On the GPU host, with `hf`, CMake, a C++ compiler, and the CUDA toolkit available:

```bash
bash scripts/install-qwen-image-2.1.sh
```

The installer pins runtime/model revisions, applies the RGBA reference-image
patch, downloads weights to `../models/image-gen/qwen-image-2.1`, and installs
`bin/sd-server-qwen-image-2.1`. It uses the INT8 ConvRot diffusion model, Q4_K_M
GGUF text encoder, F16 vision projector, and the model's VAE.

The build defaults to CUDA architecture 120; set `QWEN_IMAGE_CUDA_ARCH` for your
target hardware. `QWEN_IMAGE_BUILD_JOBS` controls build parallelism (default 3).
Runtime settings are in `serve-qwen-image.sh`:

| Variable | Default |
| --- | --- |
| `QWEN_IMAGE_GPU` | `0` |
| `QWEN_IMAGE_MAX_VRAM` | `24` GiB of managed allocations |
| `QWEN_IMAGE_STEPS` | `40` |
| `QWEN_IMAGE_MODEL_DIR` | `../models/image-gen/qwen-image-2.1` |
| `QWEN_IMAGE_SERVER` | `bin/sd-server-qwen-image-2.1` |

Leave memory for driver allocations and other resident models. Restart the
router after changing its configuration; this also unloads its workers.

## LibreChat

Image tools use `LLM_BASE_URL`, or the optional `IMAGE_GEN_OAI_BASEURL` and
`IMAGE_GEN_OAI_API_KEY` overrides. Set an endpoint reachable from the LibreChat
container. The model ID is `qwen-image-2.1`.

At startup, the renderer enables `image_gen_oai` for the existing agent selected
by `TIER1_AGENT_NAME` (default `Assistant`). It does not create an agent. For
other agents, enable **OpenAI Image Tools** in the Agent Builder. Select a
vision-capable chat model so it can inspect image results.

Recreate LibreChat after changing its environment:

```bash
docker compose -f docker-compose.server.yml up -d --no-deps librechat
```

Request transparency explicitly in the prompt as RGBA with a transparent
background. The runtime does not translate `background` or `quality` fields into
sampling settings. Output is PNG; transparency quality is experimental, so
inspect the alpha channel before relying on a clean cutout.

## Signal

The bot exposes `generate_image` and `edit_image`. Uploaded/generated images
receive conversation-scoped references retained for seven days, up to 20 per
conversation. Storage is in the bot data volume; pruning occurs when that
conversation is used. Editing accepts one reference. Supported output sizes are
1024×1024, 768×1024, and 1024×768.

`SIGNAL_IMAGE_BASE_URL` and `SIGNAL_IMAGE_API_KEY` can override the bot's LLM
endpoint settings. `SIGNAL_AGENT_TIMEOUT_S` controls its agent timeout (360
seconds by default). Cancellation prevents subsequent image delivery, though
inference may continue at the model server.

## API checks

Generate an image through llama-swap:

```bash
curl --fail http://localhost:8080/v1/images/generations \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen-image-2.1","prompt":"A red robot holding a HELLO sign","size":"1024x1024","response_format":"b64_json"}'
```

Use `scripts/check-qwen-image.py` for generation/editing checks and
`scripts/check-signal-images.py` for the bot adapter. Review their arguments
before running; inference checks load models and create output files. Save
results outside the public repository.

## Upstream terms

Model weights have their own [Qwen license](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE).
The root MIT license does not cover them. Runtime source and model details are
pinned in `scripts/install-qwen-image-2.1.sh` and the launcher.
