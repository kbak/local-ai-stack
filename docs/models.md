# Model serving

`llama-swap.yaml` defines the available models and their lifecycle groups.
`serve-*.sh` launchers contain runtime arguments. Clients use the stable model
IDs below; weights and runtime caches live outside the repository.

## Runtime layout

The Qwen and reranker launchers activate `../vllm-runtime/.venv` relative to this
checkout. They use vLLM 0.27.1-compatible arguments and Transformers 5.8-compatible
model support. Install runtime versions compatible with the selected checkpoints.
Model downloads require the upstream repository's access and license terms.

The 27B launcher loads an immutable snapshot under `../models/hf/hub`. Download
that revision using the same OS user's Hugging Face credentials before startup;
its repository and revision are in `serve-qwen-27b.sh`. Other vLLM workers can
populate their caches on first use. Muse Glimmer uses a dedicated pinned Docker
image and needs Docker access from the llama-swap process.

`PRIMARY_GPU` selects the main device (default `0`). `SECONDARY_GPU` selects the
audio/reranker device and must be set explicitly. Model memory budgets and
context limits are part of the supplied profile, not hardware detection; adjust
them together when adapting the profile to a different GPU capacity.

## Workers

| Model ID | Group | Lifetime |
| --- | --- | --- |
| `qwen3.6-35B-A3B-FP8` | `cuda0_main` | Persistent; startup default |
| `qwen3.8-27B-FP8` | `cuda0_main` | Swaps with other main chat models |
| `muse-glimmer-30B-FP8` | `cuda0_main` | Swaps with other main chat models |
| `qwen-coder-7B` | `cuda0_coder` | Persistent autocomplete |
| `qwen-image-2.1` | `cuda0_image` | Preloaded; unloads after 600 idle seconds |
| `flux-dev` | `cuda0_image` | On demand; unloads after 600 idle seconds |
| `bge-reranker-v2-m3` | `cuda1_reranker` | Persistent reranker |

Only one worker in each swappable group runs at a time. Other groups coexist
when memory permits. Group names are stable identifiers; device selection comes
from launcher settings. On a single GPU, reduce the model set or budgets before
assigning both primary and secondary workloads to it.

The chat workers enable automatic tool choice and reasoning parsers. The coder
provides FIM completion. The reranker uses vLLM's pooling runner, exposed through
`POST /upstream/bge-reranker-v2-m3/v1/score`.

The coder uses vLLM's V1 runner for WSL compatibility. The 35B worker disables the
incompatible DeepGEMM MoE path for its FP8 checkpoint. Muse Glimmer disables image
and video inputs because its configured runtime cannot complete multimodal
startup profiling. Keep these compatibility settings with the matching runtime.

## Startup and routing

`start-ai.sh` loads `.env`, starts llama-swap on `[::1]:8080`, and warms workers.
It keeps an already running main chat model; otherwise it loads the 35B model.
The image preload selects Qwen-Image. Cold compilation can take several minutes;
`healthCheckTimeout: 900` allows for it.

The UI is at `http://localhost:8080/ui`. Stack helpers choose only ready models
from `/running`; they do not select an unloaded chat model from `/v1/models`.
Memory extraction follows the largest loaded non-coder chat model.

Native model workers bind to `127.0.0.2`, while the router uses IPv6 loopback.
Configure private relays or an HTTPS proxy for remote/container clients; see
[setup](setup.md). Keep raw inference and management routes private.

## Images

See [Qwen-Image](qwen-image-2.1.md) for the pinned installer and API examples.
FLUX uses `../bin/sd-server` and these files under `../models/image-gen/`:

```text
diffusion_models/flux1-dev-fp8.safetensors
VAE/ae.safetensors
text_encoders/clip_l.safetensors
text_encoders/t5xxl_fp8_e4m3fn.safetensors
```

Supply a CUDA build of stable-diffusion.cpp compatible with the flags in
`serve-sdcpp.sh`. Weight licenses and runtime licenses are separate.
