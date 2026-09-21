# Qwen-Image 2.1

Local image generation and editing use stable-diffusion.cpp, managed by
llama-swap as `qwen-image-2.1`. Chat models continue to use vLLM. Qwen and FLUX
share `cuda0_image`: only one image model runs at a time, and it unloads after
600 seconds without requests. The main chat model and autocomplete can stay
loaded independently.

`start-ai.sh` preloads Qwen-Image as the default image model, swapping out FLUX
if it is already loaded. FLUX stays configured for on-demand use and is not
preloaded at startup. The ten-minute idle unload still applies to both models.

## AI host installation

Run from this repository on the NVIDIA GPU host:

```bash
bash scripts/install-qwen-image-2.1.sh
```

The installer requires `hf`, CMake, a C++ compiler, and a CUDA toolkit. It pins
the runtime and model revisions, downloads roughly 14 GB of weights under
`../models/image-gen/qwen-image-2.1`, and installs the executable at
`bin/sd-server-qwen-image-2.1`. The original FLUX executable is unchanged.
The CUDA architecture defaults to Blackwell SM120; set `QWEN_IMAGE_CUDA_ARCH`
when building for other GPUs. Build parallelism defaults to three jobs.

The pipeline uses the INT8 ConvRot diffusion model, the official Q4_K_M
Qwen3-VL-8B GGUF encoder, its F16 vision projector, and the Qwen-Image 2.1 VAE.
The initially tried Comfy INT8 encoder failed startup with this runtime;
use the pinned GGUF encoder and matching projector in the installer.
The dedicated runtime applies `patches/sdcpp-qwen-image-rgba.patch` to preserve
all four channels in reference uploads. Upstream's OpenAI edit handler at this
revision forces uploads to RGB, losing the transparency needed by Qwen's VAE.

Restart llama-swap to register the new entry in `llama-swap.yaml`. A restart
also unloads its language models; restore whichever main chat model was
selected before restarting. This does not require upgrading llama-swap.

`serve-qwen-image.sh` uses GPU 0, flash attention, memory-mapped weights,
automatic placement, a 24 GiB managed VRAM budget, 40 Euler steps and CFG 1.
Editing uses strength 1 so references guide a fresh generation. The upstream
example's CFG 6 and the generic server's strength 0.75 produced poor editing
results in local tests; CFG 1 matches the model's reference pipeline.
The default image size is 1024×1024. The VRAM budget applies to managed runtime
allocations; leave additional room for driver allocations and the other models.

Optional launcher overrides:

| Variable | Default | Purpose |
| --- | --- | --- |
| `QWEN_IMAGE_GPU` | `0` | GPU visible to the image worker |
| `QWEN_IMAGE_MAX_VRAM` | `24` | Managed VRAM budget, GiB |
| `QWEN_IMAGE_STEPS` | `40` | Sampling steps |
| `QWEN_IMAGE_MODEL_DIR` | `../models/image-gen/qwen-image-2.1` | Weight directory |
| `QWEN_IMAGE_SERVER` | `bin/sd-server-qwen-image-2.1` | Runtime executable |

## LibreChat host activation

The server-side changes are in `docker-compose.server.yml` and
`librechat-render.js`. Deploy these files together to the machine that actually
runs LibreChat. No LibreChat image upgrade is needed.

The image endpoint defaults to that machine's `LLM_BASE_URL`, falling back to
`https://llama.kacper.me/v1`. If necessary, set `IMAGE_GEN_OAI_BASEURL` to the
existing route to this AI host. The model name is `qwen-image-2.1` and the
placeholder key is `vllm`; override `IMAGE_GEN_OAI_API_KEY` if your route requires
authentication. Do not point a remote container at WSL's loopback address.

Recreate only LibreChat to apply its environment:

```bash
docker compose -f docker-compose.server.yml up -d --no-deps librechat
```

At startup the renderer adds `image_gen_oai` to the existing agent named `006`
(or `TIER1_AGENT_NAME`). LibreChat expands this toolkit into generation and
editing. Existing tools and saved instructions are preserved when no memory
files are available. The renderer never creates a missing agent.

For other agents, enable **OpenAI Image Tools** in the Agent Builder. That is
LibreChat's toolkit label; these settings route its calls to local Qwen, with
no OpenAI account or paid API required. Use a vision-capable chat model, such
as the current Qwen 27B, because LibreChat includes generated images in the
immediate tool result sent back to the chat model.

Example requests:

- "Create a transparent PNG sticker of a red robot holding a HELLO sign."
- Upload a photo, then ask "Change the background to a beach at sunset."
- "Make that robot blue, keeping the sign and transparent background."

The configured prompt guidance explicitly asks Qwen for RGBA transparency.
stable-diffusion.cpp does not translate the OpenAI `background` or `quality`
fields itself: include transparency in the prompt; sampling quality is set by
the launcher's step count. Output remains PNG to preserve alpha.

Transparency is experimental with this quantized runtime. The local tests
produced RGBA files, but some background areas stayed opaque white, and an
edit could make previously transparent areas opaque. Generation and color
editing worked; inspect the alpha channel before relying on clean cutouts.

## API and checks

Endpoints through the existing llama-swap listener:

- `POST /v1/images/generations`: JSON with `model`, `prompt`, `size` and `n`.
- `POST /v1/images/edits`: multipart fields `model`, `prompt`, `size` and
  `image[]` uploads. Qwen supports up to ten reference images.

Both return `data[].b64_json`. `size: "auto"` uses the launcher's default.
Explicit sizes must be divisible by 32. Start with 1024×1024; native 2K output
and large reference batches require more compute and memory. LibreChat's
built-in tool schema offers square, portrait and landscape presets.

Run an actual generation and reference-image edit with the existing Python
environment (Pillow is required):

```bash
../vllm-runtime/.venv/bin/python scripts/check-qwen-image.py
node scripts/test-librechat-render.cjs
```

The image check writes PNGs and timings to `/tmp/qwen-image-check`, validates
dimensions and PNG/RGBA output, and submits the first image to the editing
endpoint. It checks red-to-blue color change and reports transparency coverage.
Use `--require-transparency` to also require substantial transparency in both
outputs; this stricter quality check currently fails intermittently.
Inspect both images to assess edit quality.
Set `QWEN_IMAGE_API_KEY` if the endpoint requires a different bearer token.

### Local validation, 2026-09-21

The installed model passed generation and multipart editing through llama-swap
while Qwen 27B, Qwen Coder 7B and the BGE reranker stayed loaded. The existing
`https://llama.kacper.me/v1/models` route also advertised `qwen-image-2.1`.

At 1024×1024 and 40 steps, one request including model startup took 27.9 seconds;
a subsequent generation took 14.2 seconds and its reference edit took 37.1
seconds. The edit changed the robot from red to blue while preserving the
composition and HELLO sign. These are individual measurements, not a benchmark.
The primary GPU had about 18 GiB free during a sampled check with all four
models loaded. The image worker is configured to unload after ten idle minutes.

Both files were valid RGBA PNGs, but their mostly opaque backgrounds failed the
stricter transparency quality criterion. Transparency remains experimental.
The five renderer tests and Compose configuration validation passed. LibreChat
itself runs on another host, so its deployment and UI workflow remain untested.

## License and upstream references

The released weights use the [Qwen Research License](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE),
which limits use to research/evaluation and requires a separate commercial
license for commercial use.

- [Qwen-Image 2.1](https://github.com/QwenLM/Qwen-Image-2.1)
- [stable-diffusion.cpp model guide](https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/qwen_image_2.1.md)
- [LibreChat image toolkit](https://www.librechat.ai/docs/features/image_gen)
