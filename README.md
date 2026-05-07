# Local AI Stack

Self-hosted LLM stack with privacy-focused web search and research tools. Runs on a local machine and is accessible from any device on the network.

## Stack

| Service | Port | Description |
|---|---|---|
| llama-swap | 8080 | Model manager — switches between vLLM instances on demand |
| SearXNG | 8081 | Privacy-focused meta search engine |
| mcp-proxy | 8083 | MCP tool server (11 tools via streamable HTTP, no auth required) |
| location-tracker | 8084 | City-presence timeline service; exposes `get_location_at` MCP tool (bearer token required) |
| pdf-inspector | 8086 | PDF text extraction via pdf-inspector (Rust); handles Unicode, multi-column, tables |
| voice-agent | 8087 | Browser voice-chat UI with wake-word-free VAD, streaming TTS, voice picker, and full MCP tool access via strands |
| audio-api | 8088 | Shared GPU-backed Whisper (STT) + Kokoro (TTS) + Chatterbox (voice cloning) service with an OpenAI-compatible API (pinned to the secondary GPU) |
| memory-mcp | 8089 | Self-hosted agentic memory (Mem0 + bge-m3 + Qdrant) exposed as REST + MCP; Tier 2 of the hybrid memory architecture |
| image-gen | 7801 | On-demand image-generation engine (SwarmUI + Flux.1-dev). Profile-gated. Treated as an API; humans should not visit this port |
| image-gen-ui | 7802 | ChatGPT-style frontend for image-gen — the UI you actually open. Static nginx, talks to image-gen on 7801 |
| qdrant | 6333 | Vector store backing memory-mcp |
| calendar-watcher | — | Polls calendar for meal and travel events; enriches with rating/menu/weather/maps; delivers briefings via Signal |
| tg-watcher | — | Listens to a Telegram group as your user account; sends a daily LLM-generated brief via Signal |
| rss-watcher | — | Fetches RSS feeds grouped by category; sends a twice-daily LLM-generated English news brief via Signal |
| oss-watcher | — | Weekly LLM-generated summary of GitHub + Discord activity for an open-source project, delivered via Signal |
| receipt-watcher | — | Polls email accounts, extracts receipts via LLM, appends to Google Sheets, archives the message |
| MongoDB | — | LibreChat chat history storage |
| LibreChat | 3000 | Web UI, accessible from any device (speech tab wired to audio-api) |
| signal-api | 9922 | Signal REST API (bbernhard/signal-cli-rest-api, native mode) |
| signal-bot | — | Signal messenger bot powered by uoltz + local LLM (STT/TTS via audio-api) |
| yt-dlp-service | 8200 | Host-side yt-dlp download service (runs outside Docker) |

## MCP Tools

All tools are exposed via mcp-proxy on port 8083 (no authentication required — internal Docker network only). location-tracker requires a bearer token (`MCP_PROXY_AUTH_TOKEN`).

- **searxng** — web search (via local SearXNG)
- **fetch** — fetch URL content
- **arxiv** — academic paper search
- **youtube** — YouTube transcript extraction
- **time** — current time and timezone conversion
- **hackernews** — Hacker News top stories
- **pdf-inspector** — PDF text extraction (Rust, handles Unicode/multi-column/tables); available directly at port 8086, not via mcp-proxy
- **weather** — current weather and forecast
- **currency** — exchange rates
- **finance** — stock and financial data (yfinance)
- **github** — read-only access via the `gh` CLI: read files, search code and repos, browse commits/issues/PRs. Custom Python MCP server (`mcp-proxy/gh-read-server.py`) using a `GITHUB_TOKEN` injected into the `gh` config — no write paths exposed.
- **google-maps** — place search, ratings, hours, geocoding, directions (requires `GOOGLE_MAPS_API_KEY`)
- **location-tracker** — `get_location_at(datetime)` — returns city, confidence, and source for any datetime; backed by CalDAV + local LLM + SearXNG. See [`location-tracker/README.md`](location-tracker/README.md).
- **memory** — `remember(content)` / `search_memory(query, limit)` / two-step `forget` — agentic long-term memory via Mem0 + bge-m3 + Qdrant. Served from `memory-mcp` directly (not via mcp-proxy). LibreChat wires it as `http://memory-mcp:8089/mcp/mcp`; signal-bot talks to its REST surface.
- **chatterbox** — `clone_voice(text, voice, ...)` / `list_clone_voices()` — voice-cloning TTS. Served from `audio-api` at `http://audio-api:8088/mcp/mcp`. Reference samples live in the host directory configured by `VOICE_SAMPLES_DIR` and are referenced by filename stem (e.g. `joe` for `joe.wav`).

## Requirements

- Docker with Docker Compose
- [vLLM](https://github.com/vllm-project/vllm) installed in a Python venv at `~/vllm-runtime/.venv` (the launcher scripts `serve-qwen-*.sh` activate it). FP8 weights need a Hopper/Blackwell GPU (H100, RTX 6000 Ada/Pro 6000, RTX 5090, etc.).
- [llama-swap](https://github.com/mostlygeek/llama-swap) binary in PATH

## Setup

**1. Clone the repo**
```
git clone <repo-url>
cd <repo>
```

**2. Create `.env` from the example**
```
cp .env.example .env
```
Edit `.env` and set:
- Strong random values for `JWT_SECRET` and `JWT_REFRESH_SECRET`
- `GITHUB_TOKEN` — personal access token with no scopes (public repos) or `repo` scope (private). Needed for the GitHub MCP tool. Without it the tool still works but hits GitHub's unauthenticated rate limit (60 req/hr).
- `CALDAV_BASE_URL`, `CALDAV_USERNAME`, `CALDAV_PASSWORD` — CalDAV server credentials, shared by location-tracker and calendar-watcher (e.g. Nextcloud: `https://your-nextcloud/remote.php/dav`).
- `MCP_PROXY_AUTH_TOKEN` — bearer token required to access location-tracker. Generate with `openssl rand -hex 32`.
- `HOME_CITY` — your home city, used as fallback by location-tracker (e.g. `Scottsdale`).
- `CALDAV_CALENDAR_NAMES` — comma-separated calendar names to track (e.g. `Travel`). Leave empty to track all calendars.
- `GOOGLE_MAPS_API_KEY` — Google Places API (New) key for venue ratings and addresses in meal briefings.
- `MEMORY_DIR` — absolute host path for memory storage (`USER.md`, `MEMORY.md`, Qdrant volume). Keep outside the repo.
- `VOICE_SAMPLES_DIR` — absolute host path containing `.wav` reference samples for Chatterbox voice cloning. Mounted read-only into audio-api and read-write into signal-bot (so `/sample` can write new samples) at `/app/voice-samples` in both. **Required** — no default.
- `MUSIC_HOST_DIR` — absolute host path to your music library, mounted read-write into signal-bot at `/music`. **Required** — no default.
- `SECONDARY_GPU` — index or UUID of the secondary GPU. Hosts audio-api and the always-resident `qwen-coder-1.5B` autocomplete model. Defaults to `0` for single-GPU hosts.

**3. Configure models in `llama-swap.yaml`**

Each model entry shells out to a `serve-qwen-*.sh` script that activates `~/vllm-runtime/.venv` and runs `vllm serve`. Edit the launcher scripts to change vLLM args; edit `llama-swap.yaml` to add/remove models or change the group layout. The default config ships:

- **Primary GPU (`cuda0_main` group, persistent):** `qwen3.6-35B-A3B-FP8` (MoE, 3B active) — always loaded.
- **Primary GPU (`cuda0_ondemand` group):** `qwen3.6-27B-FP8` dense — loads on first request, stays resident. Coexists on the same card with the 35B because both run with modest `--gpu-memory-utilization` (0.45–0.50).
- **Secondary GPU (`cuda1` group, persistent):** `qwen-coder-1.5B` (Qwen2.5-Coder-1.5B-Instruct, FP16) for FIM tab-complete — always loaded so tab-complete never pays a cold-start cost. Coexists on the same card with audio-api (Whisper + Kokoro + Chatterbox).

The chat launchers (`serve-qwen-27b.sh`, `serve-qwen-35b-a3b.sh`) use:
- `--max-model-len 131072` (27B) / `262144` (35B) — full FP16 KV cache
- `--max-num-seqs 2` — single-user, low concurrency
- `--gpu-memory-utilization 0.45`–`0.50` — leaves headroom for the second model on the same GPU
- `--reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_xml` — proper tool-call handling for LibreChat
- Stock FP8 weights (`Qwen/Qwen3.6-27B-FP8`, `Qwen/Qwen3.6-35B-A3B-FP8`) — `--structured-outputs-config.backend=auto` defaults to xgrammar on FP8, which keeps tool-call JSON well-formed (community AWQ/NVFP4 quants of these models exhibit a tool-call collapse pathology, which is why we stick with stock FP8)

The coder model pins itself to the secondary GPU via `CUDA_VISIBLE_DEVICES=${env.SECONDARY_GPU}`. The launcher resolves UUIDs to numeric indices (vLLM 0.20.1 chokes on UUIDs in `CUDA_VISIBLE_DEVICES`).

**4. Start the Docker stack**
```
docker compose up -d --build
```

First startup takes a few minutes — mcp-proxy builds a custom image that pre-installs all MCP packages and the `gh` CLI (used by the custom read-only GitHub MCP server at `mcp-proxy/gh-read-server.py`).

**5. Start llama-swap**
```
llama-swap --config llama-swap.yaml
```

llama-swap listens on port 8080 and launches a `vllm serve` subprocess on demand when a model is requested. Inside a group, requesting a different model swaps out the current one (`swap: true`). Models in separate `persistent: true` groups stay resident alongside each other — used here to keep the 35B-A3B chat model on the primary GPU and the autocomplete coder model on the secondary GPU loaded concurrently. Cold start of a vLLM model can take 5–10 minutes (compile cache miss); `healthCheckTimeout: 900` accommodates this.

**6. Open LibreChat**

Navigate to `http://localhost:3000` (or `http://<server-ip>:3000` from another device) and register an account. The `default` model in `librechat.yaml` is `qwen3.6-35B-A3B`; every model defined in `llama-swap.yaml` is fetched dynamically and shown in the model dropdown.

## llama-swap web UI

llama-swap has a built-in UI for monitoring and manually loading/unloading models:
```
http://localhost:8080/ui
```

## GPU layout

Two GPUs are partitioned across services via `CUDA_VISIBLE_DEVICES` (set at the container level for audio-api and per-model in llama-swap via `${env.SECONDARY_GPU}`):

- **Primary GPU:** llama-swap chat/agent models. The 35B-A3B is always-loaded (`cuda0_main`, persistent); the 27B dense model is on-demand but sticky (`cuda0_ondemand`, no swap target). Both coexist via modest `--gpu-memory-utilization` settings.
- **Secondary GPU (`SECONDARY_GPU`):** audio-api (Whisper + Kokoro + Chatterbox) and the autocomplete coder model `qwen-coder-1.5B`, all resident together.

The `groups` block in `llama-swap.yaml` keeps the coder model in its own `persistent: true` group so loads/unloads on the primary GPU never evict it — tab-complete never pays a cold-start cost.

Single-GPU hosts work fine: leave `SECONDARY_GPU=0` and everything coexists on one card (mind the VRAM budget).

## VS Code / Continue.dev

Point [Continue.dev](https://continue.dev) at llama-swap for chat + tab-completion using the same models the rest of the stack uses. Drop this into `%USERPROFILE%\.continue\config.yaml`:

```yaml
name: Local Stack
version: 1.0.0
schema: v1

models:
  - name: Qwen 3.6 27B
    provider: openai
    model: qwen3.6-27B-FP8
    apiBase: http://127.0.0.1:8080/v1
    apiKey: dummy
    roles: [chat, edit, apply]

  - name: Qwen Coder 1.5B
    provider: openai
    model: qwen-coder-1.5B
    apiBase: http://127.0.0.1:8080/v1
    apiKey: dummy
    roles: [autocomplete]

tabAutocompleteOptions:
  maxPromptTokens: 2048
  maxSuffixPercentage: 0.3
  debounceDelay: 250
  multilineCompletions: auto
  useCache: true
```

The model `id`s must match the llama-swap.yaml entries exactly. `qwen-coder-1.5B` runs on the secondary GPU at ~150 t/s (≈200–400 ms tab-complete latency); chat/edit/agent use Qwen 3.6 27B on the primary GPU.

MCP servers can also be wired into Continue via per-server YAMLs in `.continue/mcpServers/` (committed in this repo: `github.yaml`, `searxng.yaml`, `time.yaml`).

## Connecting MCP tools from external clients

mcp-proxy exposes each MCP server at its own streamable-http endpoint. Wire them into any MCP client (Continue.dev, Claude Desktop, etc.) by URL:

```
http://<server-ip>:8083/servers/searxng/mcp
http://<server-ip>:8083/servers/time/mcp
http://<server-ip>:8083/servers/github/mcp
# etc.
```

## audio-api (shared STT/TTS + voice cloning)

A single GPU-backed service exposing OpenAI-compatible endpoints — used by LibreChat, signal-bot, and voice-agent. Three models load once at startup and stay warm:

- **Whisper** (faster-whisper) — speech-to-text
- **Kokoro** (kokoro-onnx) — fast streaming TTS, fixed voice library
- **Chatterbox** — voice-cloning TTS; clones from a short reference `.wav` in English plus 22 other languages

Endpoints:

- `POST /v1/audio/transcriptions` — Whisper transcription (OpenAI-compatible)
- `POST /v1/audio/speech` — Kokoro TTS; supports `stream: true` for sentence-by-sentence chunks
- `POST /v1/audio/clone` — Chatterbox voice cloning. Body: `{text, voice, language, exaggeration, cfg_weight, response_format}`. `voice` is a filename stem under `VOICE_SAMPLES_DIR` (e.g. `joe` → `joe.wav`) or an absolute `.wav` path; omit it for Chatterbox's built-in default voice. `language` defaults to `"en"` and routes to the English-only model; any other code routes to the multilingual model (`ar, da, de, el, es, fi, fr, he, hi, it, ja, ko, ms, nl, no, pl, pt, ru, sv, sw, tr, zh`). The reference voice can be in any language — only `text`'s language matters. Output formats: `wav`, `mp3`, `ogg`/`opus`, `aac`/`m4a`, `flac`, `pcm`.
- `GET /v1/voices` — `{voices, default, lang, speed}` — installed Kokoro voices plus the current server-side defaults
- `GET /v1/voices/clone` — `{voices, voice_dir, languages}` — `.wav` files discovered under `VOICE_SAMPLES_DIR` and the language codes accepted by `/v1/audio/clone`
- `GET /health` — returns 200 only once all three models are loaded AND warmed up (CUDA kernels JIT-compiled). `start.sh` waits for `Chatterbox warmup complete` in the logs before considering audio-api ready.
- `POST /mcp/mcp` — MCP streamable-http surface exposing `clone_voice` and `list_clone_voices` as tools (LibreChat wires this as the `chatterbox` server).

Defaults in `audio-api.env` (**single source of truth** for voice/lang/speed):

```
WHISPER_MODEL=distil-large-v3
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
ONNX_PROVIDER=CUDAExecutionProvider
DEFAULT_VOICE=bm_george
DEFAULT_LANG=b
DEFAULT_SPEED=1.0
```

Callers (voice-agent, calendar-watcher, rss-watcher, etc.) omit `voice`/`lang`/`speed` from their requests so these defaults apply. Pass them explicitly only to override per-request. To change the stack-wide default voice, edit `DEFAULT_VOICE` here and `docker compose restart audio-api` — no other service needs updating. `signal-bot` is the one exception (it reads `TTS_VOICE` from `signal-bot.env` because the uoltz upstream expects it); `librechat.yaml` also pins a UI default under `speechTab.textToSpeech.voice`.

All three models run on the GPU. Post-warmup, first Kokoro request latency is ~0.7s; Chatterbox is heavier (≈seconds-per-sentence on first cold call, faster afterwards because the CUDA arena was pre-sized at warmup). Long sentences are auto-chunked at commas/whitespace before hitting Kokoro's 510-token cap.

**Chatterbox dual-model layout.** audio-api loads two Chatterbox variants — the English-only model and the 23-language multilingual model — but they **share the same `s3gen` vocoder and `VoiceEncoder` instances on the GPU**. Only the T3 transformer (~2.1 GB) and tokenizer differ between them, so the combined VRAM footprint is ~5.5 GB instead of ~7 GB for two independent loads. The English model handles `language="en"`; everything else goes through the multilingual model. The first non-English request is slightly slower (multilingual T3 kernels JIT on first use); subsequent ones run at steady state.

**Voice cloning samples.** Drop reference `.wav` files into the host directory you set as `VOICE_SAMPLES_DIR` (mounted read-only at `/app/voice-samples`). Five to fifteen seconds of clean speech per voice works well. The filename stem becomes the `voice` argument: `joe.wav` → `clone_voice(text=..., voice="joe")`. The reference clip's language doesn't have to match `text`'s language — Chatterbox extracts speaker timbre from the audio prompt and synthesises whatever you ask in the target language.

## voice-agent (browser voice chat)

A self-hosted voice-chat web UI at `http://<host>:8087` — tap the mic, talk, hear the answer. Same MCP tools LibreChat has, loaded via `signal-bot-custom-skills/` through the strands framework.

**Features**
- Browser-side RMS VAD — no push-to-talk, recording stops on ~1.2s of silence
- Streaming MP3 TTS via MediaSource API — audio starts playing within ~200ms of the first sentence
- **Conversation mode** (`auto: on`) — mic auto-reopens after each bot reply; one tap for a full back-and-forth
- Voice picker — populated live from audio-api's `/v1/voices`, choice persists in localStorage
- Interrupt / reset / per-session voice override
- Fixed-position header/footer so mobile browser chrome doesn't eat the controls

**Architecture**
```
browser ── WS ──► voice-agent ──► audio-api (STT)
                       │
                       ▼
                 strands Agent (Qwen + all MCP tools)
                       │
                       ▼
                  audio-api (TTS, streamed MP3) ──► browser
```

- 60s agent timeout with `invoke_async` — stop button truly cancels
- `enable_thinking: false` passed via `chat_template_kwargs` so Qwen skips the reasoning phase in voice mode (much faster, no tool loops)
- Static `./voice-agent/static/` is mounted live — CSS/JS edits apply without rebuild

**Phone access via Tailscale**

The PC has no mic, but your phone does. Serve over HTTPS (required for browser mic access):

```
tailscale serve --bg --https=8443 http://localhost:8087
```

Then open `https://<pc-name>.<tailnet>.ts.net:8443` on your phone.

LibreChat serves on `:443` via Tailscale — voice-agent is on `:8443` to avoid the collision.

## image-gen (on-demand image generation)

Two profile-gated containers that come up together:

- **`image-gen`** (port 7801) — the engine. SwarmUI fronting a hidden ComfyUI backend; pure JSON API, no human UI exposed.
- **`image-gen-ui`** (port 7802) — a tiny nginx-served static frontend in the spirit of ChatGPT/Claude: prompt textarea, four-image grid per prompt, click for full size, history persisted in localStorage. Talks to the engine over its WebSocket API.

**Use it on demand**, after manually unloading the main chat model:
```
curl -s http://localhost:8080/unload     # frees the primary GPU
./img.sh                                  # foreground; Ctrl+C stops both
```
Then open **`http://localhost:7802`**. (Don't bother with 7801 — it's the engine, not for humans.)

The launcher prints VRAM status before and after, warns if a main-group LLM is still resident, and ensures both containers are stopped on exit (Ctrl+C, error, or shell close).

### Hardware

Runs on the primary GPU (`PRIMARY_GPU` in `.env`, defaults to `0`). Built against `nvidia/cuda:12.8.1-runtime-ubuntu24.04` so it works on Blackwell (RTX 5090 / 5060 Ti — older `cu126` images crash with `no kernel image is available`). At fp8 the model uses ~12 GB; at fp16 closer to ~28 GB.

### One-time model setup

Drop the Flux.1-dev fp8 weights and the Comfy-Org text encoders into `${IMAGE_DIR}` on the host (the path you set in `.env`). All four files are ungated — no HuggingFace token required.

```
${IMAGE_DIR}/
├── unet/flux1-dev-fp8.safetensors                  (~12 GB)
├── vae/ae.safetensors                              (~335 MB)
├── clip/clip_l.safetensors                         (~250 MB)
└── clip/t5xxl_fp8_e4m3fn.safetensors               (~4.9 GB)
```

Quick download via `huggingface-cli`:
```
huggingface-cli download Comfy-Org/flux1-dev flux1-dev-fp8.safetensors \
    --local-dir ${IMAGE_DIR}/unet
huggingface-cli download Comfy-Org/Lumina_Text_Encoders \
    t5xxl_fp8_e4m3fn.safetensors clip_l.safetensors \
    --local-dir ${IMAGE_DIR}/clip
huggingface-cli download Comfy-Org/flux1-schnell ae.safetensors \
    --local-dir ${IMAGE_DIR}/vae
```

(Adjust to match the file layout your build of SwarmUI expects — SwarmUI's first-launch wizard will offer to download Flux for you and lay the directory out automatically. The list above is what you'd get.)

### First launch

The first `./img.sh` does a one-time setup inside SwarmUI:
- ComfyUI backend is fetched and a Python venv is created with cu128 PyTorch wheels (~5 minutes).
- SwarmUI auto-detects the model files in `${IMAGE_DIR}` and registers them.
- The first time you visit `http://localhost:7801` directly (only needed once), SwarmUI's setup wizard runs — pick `just_self`, backend `comfyui`, theme of your choice, **set Flux.1-dev fp8 as the default model**.

After that, never visit 7801 again. Open `http://localhost:7802` and the custom UI handles the rest.

Subsequent launches are fast — both ComfyUI and SwarmUI start in seconds. Output images are persisted to the `image-gen-output` Docker volume.

### Editing the UI

`image-gen-ui/static/` is bind-mounted read-only into the nginx container, so HTML/CSS/JS edits apply with a hard refresh (Ctrl+Shift+R) — no rebuild needed. The backend SwarmUI URL is computed from the page origin (`<host>:7801`), so the UI works unchanged whether accessed via `localhost`, the LAN IP, or a Tailscale name.

## Signal Bot

A Signal messenger bot that routes messages through the local LLM with the same MCP tools available in LibreChat. Built on a [custom fork of uoltz](https://github.com/kbak/uoltz), cloned at Docker build time.

### Setup

**1. Register a Signal number with signal-api**

Start signal-api first, then link or register a number:
```
# Link an existing Signal account (scan QR code)
docker compose up -d signal-api
docker exec -it signal-api signal-cli-rest-api link -n "006-bot"
```

The account data is stored in the `signal-cli-data` volume and persists across restarts.

**2. Configure signal-bot.env**
```
cp signal-bot.env.example signal-bot.env
```
Set `SIGNAL_NUMBER` to your registered Signal number (international format, e.g. `+14155551234`).

Set `BRIEFING_RECIPIENT` to the Signal number that should receive all briefings (calendar-watcher, tg-watcher, etc.). This can be the same number.

Optionally set `ALLOWED_NUMBERS` to restrict who can use the bot (comma-separated list). Leave unset to allow anyone who messages the number.

Set `GITHUB_TOKEN` to the same token as in `.env` (the signal-bot calls the GitHub API directly, independently of mcp-proxy).

**3. Build and start**
```
docker compose up -d --build signal-bot
```

### Group chat

The bot responds in groups in two ways:
- **Prefix**: message starts with `BOT_GROUP_PREFIX` (default: `@006`)
- **Mention**: the bot's number is @mentioned in the message

### Latency

The bot polls for new messages every 1 second with a 1-second receive timeout, giving ~0.5s average wait before the LLM starts processing. This is close to LibreChat's HTTP-based latency.

### Custom skills

Skills in `signal-bot-custom-skills/` are mounted into the container at `/app/data/custom_skills` and auto-discovered at startup alongside uoltz's built-ins. Each skill is a directory with a `skill.yaml` and a Python file.

The uoltz fork ships with several built-ins disabled by default (`web_search`, `notes`, `rss_digest`, `shell`, `skill_builder`) — the stack intentionally keeps them off: web search, news digests, and host-side actions are handled by MCP tools and watcher services instead.

Available custom skills: arxiv, currency, finance, github, google_maps, hackernews, music_download, pdf, roast, sample_download, searxng, time, tts_clone, voices_list, weather.

Most are thin MCP-client shims that call mcp-proxy on port 8083. A few do their own thing:

- **github** — calls the GitHub REST API directly (not via mcp-proxy) using `GITHUB_TOKEN` from the environment.
- **music_download** (`/music`) — downloads songs from Shazam or Spotify links as high-quality MP3, trims non-music content from start/end, classifies into a configured directory, and sets ID3 tags including cover art. See setup below.
- **sample_download** (`/sample`) — downloads a short clip from a YouTube link and saves it as a `.wav` voice sample for cloning. See setup below.
- **voices_list** (`/voices`) — lists the voice samples currently saved under `VOICE_SAMPLES_DIR`.
- **tts_clone** (`/tts`) — synthesises a Signal voice note from text using one of your saved voice samples. Auto-detects the language (`lingua`) or accepts an explicit ISO code as the first token. Voice hint is greedy fuzzy-matched against `VOICE_SAMPLES_DIR`. See setup below.
- **roast** (`/roast`) — LLM-driven roast battle between two saved voices, delivered as a stitched Signal voice note. Resolves personas via the LLM (with MCP-tool research) and caches them on disk; preserves the duel.py mechanics (repetition detection, periodic pivots, stall recovery via forced tool calls). See setup below.
- **pdf** — calls the pdf-inspector service directly on port 8086.

Shared helpers used by `music_download` and `sample_download` (yt-dlp client, filename utilities, LLM client) live in `signal-bot-custom-skills/_shared/`. The skill loader skips underscore-prefixed directories, so `_shared/` is import-only.

For details on the patches applied to the uoltz fork, see the [kbak/uoltz README](https://github.com/kbak/uoltz).

### Voice messages

Voice transcription and synthesis are delegated to **audio-api** over HTTP — signal-bot no longer bundles Whisper or Kokoro, has no GPU reservation, and stays under ~1.5GB of RAM. Set `AUDIO_API_URL=http://audio-api:8088` and pick a default voice with `TTS_VOICE=bm_george` in `signal-bot.env` (uoltz reads this var directly).

### Music download skill

Downloads songs from Shazam/Spotify links (or screenshots of either app) as MP3 files into your local music library.

**Usage**
```
/music https://shazam.com/track/...
/music https://open.spotify.com/track/...
/music house https://shazam.com/track/...     # inline genre hint
```
Or send a screenshot of Shazam/Spotify with `/music` as the caption.

**Setup**

1. **yt-dlp service** — runs on the host (outside Docker) to avoid YouTube IP blocks:
   ```
   cd yt-dlp-service
   pip install -r requirements.txt
   python server.py
   ```
   Listens on port 8200. Start this before the bot.

2. **YouTube cookies** — export from Firefox while logged into YouTube (Brave doesn't work due to app-bound encryption):
   ```
   yt-dlp --cookies-from-browser firefox --cookies yt-dlp-service/youtube_cookies.txt --skip-download "https://www.youtube.com"
   ```
   Cookies expire after weeks/months — re-run this command when downloads start failing.

3. **Music library volume** — set `MUSIC_HOST_DIR` in your environment or a root `.env` file to the host path of your music library:
   ```
   MUSIC_HOST_DIR=D:/backup/Music
   ```
   This is mounted at `/music` inside the signal-bot container.

4. **Configure `signal-bot.env`**:
   ```
   MUSIC_DIRS=rock:Rock,top40:Top 40
   MUSIC_CLASSIFY_PROMPT="rock -> rock; everything else -> top40"
   YTDLP_SERVICE_URL=http://host.docker.internal:8200
   ```

### Voice sample skill

Downloads a short clip from a YouTube link and saves it as a `.wav` under `VOICE_SAMPLES_DIR` so audio-api can use it for voice cloning.

**Usage**
```
/sample <youtube-url> <length>                   # length only; start = URL ?t= or 0
/sample <youtube-url> <start> <length>           # explicit start
/sample <youtube-url> <start> <length> <name>    # override the auto-detected name
```
Timestamps may be `hh:mm:ss`, `mm:ss`, or `ss`. The bot auto-names the saved file `<firstname_lastname>.wav` from the YouTube title; on collision a numeric suffix is appended (e.g. `obama (2).wav`). Aim for 5–15 seconds of clean speech for the best clone quality.

```
/voices                                          # list samples already saved
```

**Setup**

Reuses the same yt-dlp service as `/music` (see above) — no extra services. `VOICE_SAMPLES_DIR` must be set in `.env`; it is mounted read-write into signal-bot at `/app/voice-samples` (and read-only into audio-api at the same path).

### TTS clone skill

Synthesises a Signal voice note from text using Chatterbox voice cloning. Sends back as an ogg/opus voice attachment (the bubble-with-play-button kind, not a file).

**Usage**
```
/tts <voice-hint> <text>            # auto-detect text language
/tts <lang> <voice-hint> <text>     # force language (en, pl, de, fr, ...)
/tts <name>.wav <text>              # explicit voice file, no fuzzy match
```
Examples:
```
/tts barack obama Hello there. This is a cloning test.
/tts pl barack obama Cześć, to jest test.
/tts barack This is a single-token prefix that uniquely matches barack_obama.wav.
```

The voice hint is greedy fuzzy-matched against the filename stems under `VOICE_SAMPLES_DIR` (case-insensitive, diacritic-insensitive, accepts any subset of the words in the stem — so `obama`, `barack`, or `barack obama` all hit `barack_obama.wav`). Whatever's left after the match is the text.

The first token is treated as a 2-letter ISO language code only if it's exactly two characters AND in Chatterbox's supported set (`ar, da, de, el, en, es, fi, fr, he, hi, it, ja, ko, ms, nl, no, pl, pt, ru, sv, sw, tr, zh`). Otherwise auto-detect runs. Text is capped at ~2700 chars (~3 minutes of speech).

This skill needs the `signal` and `sender` kwargs that the `kbak/uoltz` fork injects into direct skills (since the bot's standard reply path only sends text). Other forks would need a small `bot.py` patch — see [the upstream commit](https://github.com/kbak/uoltz/commit/0423314) for the 2-line change.

### Roast battle skill

LLM-driven roast battle between two voices you've already saved. Both agents stay fully in character, take turns trading roasts, and can pull MCP tools (search, fetch, hackernews, etc.) for fresh material when they get stuck. The transcript is sent as a text message first; the stitched voice note follows.

**Usage**
```
/roast <person1>, <person2>
/roast <person1>, <person2> <turns>
/roast <person1>, <person2> <turns> <topic...>
/roast <lang> <person1>, <person2> [turns] [topic...]
```
Examples:
```
/roast hillary clinton, donald trump
/roast hillary clinton, donald trump 8
/roast hillary clinton, donald trump 8 better than you
/roast pl hillary clinton, donald trump 10 lepsza niz ty
```

The first token is treated as a language code only if it's exactly two ASCII chars and in Chatterbox's supported set. Comma is required between the two names. The turns slot must be an integer (`2..30`); default `6`. Anything after the integer (or after the second name, if no integer is given) is the topic. **If you omit the topic, the LLM invents one** for the two named combatants — usually pretty good.

**Mechanics preserved from the original duel.py**
- Random opening agent, opening meta-prompt embedding the topic.
- Repetition detection (difflib SequenceMatcher) — if a turn looks too similar to recent ones, the next agent gets a forced "drop it, fresh angle" pivot prompt.
- Periodic pivot every 5 successful turns to prevent agents from camping a single bit.
- Stall recovery: if a turn produces empty output, the next turn is forced to call an MCP tool (search/fetch/etc.) to inject fresh material.
- `<think>...</think>` blocks are stripped from streamed output before being added to history (qwen3-style models).

**Voice + persona resolution**
- Voices are resolved from the user's input via the same greedy fuzzy match `/tts` uses, against `VOICE_SAMPLES_DIR`. So `/roast donald trump, joe biden` finds `donald_trump.wav` and `joe_biden.wav`.
- Personas are LLM-generated once per name and cached at `/app/data/persona_cache/<slug>.txt` inside the bot (signal-bot-data volume). Delete the file to force a regeneration.

**Model**
Picks the largest currently-running non-coder chat model via `stack_shared.llm_model.resolve_model()` — the same helper every other watcher uses. No need to pin a model in the skill.

**Latency**
A 6-turn roast typically takes 30–60s end to end (persona-resolution rounds + 6 LLM turns + 6 audio-clone calls + ffmpeg stitch). The audio synthesis dominates after caching.

## calendar-watcher

Polls CalDAV calendars and sends Signal briefings for:

- **Meal events** — detected restaurant bookings get enriched with Google Places rating, menu URL, weather, and a Google Maps link. The calendar event is patched with a 🍽 emoji prefix, the Places-resolved address (if the location field was empty or vague), and a Maps URL.
- **Travel anchors** — first flight or arrival event to a new city gets a weather forecast sent 24h before departure via Signal. The calendar event is patched with a ✈️ emoji prefix. Connecting flights (another flight departing within 6h) are skipped.

Requires `CALDAV_BASE_URL`, `CALDAV_USERNAME`, `CALDAV_PASSWORD`, `CALDAV_CALENDAR_NAMES`, `GOOGLE_MAPS_API_KEY` in `.env`, and `SIGNAL_NUMBER`, `BRIEFING_RECIPIENT` in `signal-bot.env`.

## tg-watcher

Passively listens to a Telegram group using your own user account (no bot added to the group) and delivers a daily LLM-generated brief via Signal.

- Collects all text messages into a local SQLite DB
- Every morning at the configured time, summarises the last 24h with the local LLM and sends it to your Signal number
- Messages older than 48h are pruned after each summary run

### Setup

**1. Get Telegram API credentials**

Go to [https://my.telegram.org](https://my.telegram.org) → "API development tools" and create an app. Note your `api_id` and `api_hash`.

**2. Find your group ID**

Forward any message from the target group to [@userinfobot](https://t.me/userinfobot) on Telegram. It will reply with a negative numeric ID (e.g. `-1001234567890`).

**3. Configure tg-watcher.env**
```
cp tg-watcher.env.example tg-watcher.env
```
Set `TG_API_ID`, `TG_API_HASH`, `TG_PHONE`, and `TG_GROUP`. Adjust `SUMMARY_CRON_HOUR`/`SUMMARY_CRON_MINUTE` (UTC) if needed — default is 12:00 UTC (5:00 AM MST).

LLM and Signal settings are inherited from `signal-bot.env` — no need to repeat them.

**4. One-time interactive login**

Telethon requires an interactive login the first time to verify your phone number:
```
docker compose run --rm -it tg-watcher python auth.py
```
Enter the code Telegram sends you. The session is saved to the `tg-watcher-data` volume and persists across restarts — `TG_PHONE` can be removed from the env file after this.

**5. Start**
```
docker compose up -d tg-watcher
```

**6. Test the summary without waiting**
```
docker compose exec tg-watcher python -c "from tg_watcher.summarizer import run_summary; run_summary()"
```

## rss-watcher

Fetches RSS feeds grouped by category and delivers a twice-daily LLM-generated English news brief via Signal. Briefs fire at 00:05 and 12:05 UTC, covering items from the preceding 12 hours. Non-English articles are translated by the LLM.

LLM and Signal settings are shared with signal-bot via `signal-bot.env` — no duplication needed.

### Setup

**1. Configure rss-watcher.env**
```
cp rss-watcher.env.example rss-watcher.env
```

Set `RSS_FEEDS` to a JSON object mapping category names to lists of feed URLs:
```json
{
  "technology": ["https://feeds.arstechnica.com/arstechnica/index", "https://www.theverge.com/rss/index.xml"],
  "general":    ["https://feeds.bbci.co.uk/news/rss.xml"],
  "cars":       ["https://www.motortrend.com/feeds/all/"]
}
```

Each category is summarised independently, so topic grouping is consistent within a category. The Signal message sections are separated by `---`.

**2. Start**
```
docker compose up -d rss-watcher
```

**3. Test immediately without waiting**
```
docker compose exec rss-watcher python -c "from rss_watcher.briefer import run_news_brief; run_news_brief()"
```

## memory-mcp

Self-hosted agentic memory. Mem0 is the memory framework (extract → dedup → store), bge-m3 is the CPU embedding model, Qdrant is the vector store. Exposes a REST API *and* an MCP streamable-http server on the same port (8089).

- REST: `/health`, `/v1/memory` (POST add, GET list), `/v1/memory/search`, `/v1/memory/{id}` DELETE. signal-bot's memory skill uses this surface.
- MCP: `/mcp/mcp` (not `/mcp/`). LibreChat wires it as `http://memory-mcp:8089/mcp/mcp`.

Memories live under `${MEMORY_DIR}` on the host. The directory also contains `USER.md` + `MEMORY.md`, which LibreChat and signal-bot inject as always-on Tier 1 memory — `librechat-render.js` pulls them into every agent's system prompt at container boot.

## oss-watcher

Weekly brief covering a single open-source project: merged PRs, notable open PRs, issues, and Discord discussion themes. Fires once a week (default: Monday 08:00 UTC) via APScheduler.

### Setup

**1. Configure `oss-watcher.env`**
```
cp oss-watcher.env.example oss-watcher.env
```

Required:
- `GITHUB_REPO` — `owner/repo` to watch
- `DISCORD_TOKEN` — Discord user token (Settings → Advanced → copy from network tab)
- `DISCORD_CHANNEL_ID` — target channel (right-click → Copy Channel ID, requires Developer Mode)

LLM and Signal settings are inherited from `signal-bot.env`.

**2. Start**
```
docker compose up -d oss-watcher
```

## receipt-watcher

Polls email accounts (Gmail API or plain IMAP), extracts receipt data from whitelisted vendors via the local LLM, appends rows to a Google Sheets expense sheet, and archives the message. Backend-agnostic — same pipeline against multiple accounts.

### Setup

**1. Configure `receipt-watcher.env`** (LLM + Signal settings inherited from `signal-bot.env`).

**2. Populate the two YAML configs** in `receipt-watcher/`:
- `accounts.yaml` — per-inbox auth (Gmail OAuth or IMAP app password) + sheet routing
- `vendors.yaml` — global domain → vendor + category whitelist. Senders not in this list are skipped, so the service *is* the filter — no Gmail labels or IMAP rules needed.

**3. Secrets** — drop Google service account JSON + Gmail OAuth tokens into `receipt-watcher/secrets/` (mounted read-only).

**4. Start**
```
docker compose up -d receipt-watcher
```

Low-confidence extractions are left in the inbox with a Signal "review manually" alert rather than written to the sheet. The service never archives before the sheet write lands, so any failure leaves the email visible.

## llm-kb-template

A minimal scaffold for building an LLM-curated personal knowledge base. The folder contains:

- `CLAUDE.md` — the schema and workflows the agent follows (rename to `AGENTS.md` for non-Claude tools)
- `GUIDE.md` — step-by-step usage instructions
- `raw/` — drop source documents here; the agent treats this directory as immutable
- `wiki/` — agent-owned compiled wiki with frontmatter, `[[backlinks]]`, an `index.md`, and an append-only `log.md`
- `outputs/` — generated reports, lint runs, query answers

Workflow: copy the template into a new folder, customize the focus areas in `CLAUDE.md`, dump sources into `raw/`, then ask the agent to ingest, query, or run a monthly lint pass per the prompts in `GUIDE.md`. Standalone — not wired into the running stack.

## Notes

- LibreChat chat history is persisted in MongoDB (`mongodb-data` volume) — survives container restarts
- MCP package cache is persisted — tool calls are fast after first use
- SearXNG runs locally — no search queries leave your network
- llama-swap unloads the previous model within a group when another is requested; a separate persistent group on the secondary GPU keeps the coder autocomplete model resident alongside whichever chat model the `main` group is running
- signal-cli-data volume is shared between signal-api (read-write) and signal-bot (read-only)
- mcp-proxy bundles `uvx` for Python-based MCP servers and the `gh` CLI for the custom read-only GitHub server (`mcp-proxy/gh-read-server.py`). No Node.js dependency anymore
- audio-api is the single GPU consumer for STT/TTS/voice-cloning — signal-bot, LibreChat, and voice-agent all call it over HTTP
- audio-api owns the default voice/lang/speed (`DEFAULT_VOICE` in `audio-api.env`). voice-agent and the watchers omit these fields so the server-side defaults apply; `signal-bot.env` still sets `TTS_VOICE` (uoltz reads it) and `librechat.yaml` pins a UI default. To swap voices stack-wide, change `DEFAULT_VOICE` and restart audio-api
- `./shared/` is bind-mounted (`:ro`) into every watcher (`calendar-watcher`, `tg-watcher`, `oss-watcher`, `rss-watcher`, `receipt-watcher`, `location-tracker`) and installed editable — edit `shared/stack_shared/*.py` and `docker compose restart <watcher>` without rebuilding the image
- memory-mcp and audio-api both expose REST + MCP on a single port. MCP clients use `/mcp/mcp` (audio-api: `clone_voice`; memory-mcp: `remember`, `search_memory`, two-step `forget`); REST clients use `/v1/...`
