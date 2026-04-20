# Local AI Stack

Self-hosted LLM stack with privacy-focused web search and research tools. Runs on a local machine and is accessible from any device on the network.

## Stack

| Service | Port | Description |
|---|---|---|
| llama-swap | 8080 | Model manager — switches between llama-server instances on demand |
| SearXNG | 8081 | Privacy-focused meta search engine |
| mcp-proxy | 8083 | MCP tool server (14 tools via streamable HTTP, no auth required) |
| location-tracker | 8084 | City-presence timeline service; exposes `get_location_at` MCP tool (bearer token required) |
| pdf-inspector | 8086 | PDF text extraction via pdf-inspector (Rust); handles Unicode, multi-column, tables |
| voice-agent | 8087 | Browser voice-chat UI with wake-word-free VAD, streaming TTS, voice picker, and full MCP tool access via strands |
| audio-api | 8088 | Shared GPU-backed Whisper (STT) + Kokoro (TTS) service with an OpenAI-compatible API |
| calendar-watcher | — | Polls calendar for meal and travel events; enriches with rating/menu/weather/maps; delivers briefings via Signal |
| tg-watcher | — | Listens to a Telegram group as your user account; sends a daily LLM-generated brief via Signal |
| rss-watcher | — | Fetches RSS feeds grouped by category; sends a twice-daily LLM-generated English news brief via Signal |
| MongoDB | — | LibreChat chat history storage |
| LibreChat | 3000 | Web UI, accessible from any device (speech tab wired to audio-api) |
| signal-api | 9922 | Signal REST API (bbernhard/signal-cli-rest-api, native mode) |
| signal-bot | — | Signal messenger bot powered by uoltz + local LLM (STT/TTS via audio-api) |
| yt-dlp-service | 8200 | Host-side yt-dlp download service (runs outside Docker) |

## MCP Tools

All tools are exposed via mcp-proxy on port 8083 (no authentication required — internal Docker network only). location-tracker requires a bearer token (`MCP_PROXY_AUTH_TOKEN`).

- **searxng** — web search (via local SearXNG)
- **fetch** — fetch URL content
- **wikipedia** — Wikipedia search and lookup
- **arxiv** — academic paper search
- **youtube** — YouTube transcript extraction
- **time** — current time and timezone conversion
- **hackernews** — Hacker News top stories
- **pdf-inspector** — PDF text extraction (Rust, handles Unicode/multi-column/tables); available directly at port 8086, not via mcp-proxy
- **semantic-scholar** — academic paper search
- **patents** — patent search
- **weather** — current weather and forecast
- **currency** — exchange rates
- **finance** — stock and financial data (yfinance)
- **github** — read files, search code and repos, browse commits and issues (requires `GITHUB_TOKEN`)
- **google-maps** — place search, ratings, hours, geocoding, directions (requires `GOOGLE_MAPS_API_KEY`)
- **location-tracker** — `get_location_at(datetime)` — returns city, confidence, and source for any datetime; backed by CalDAV + local LLM + SearXNG. See [`location-tracker/README.md`](location-tracker/README.md).

## Requirements

- Docker with Docker Compose
- [llama.cpp](https://github.com/ggml-org/llama.cpp) with `llama-server` in PATH
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

**3. Configure models in `llama-swap.yaml`**

Edit `llama-swap.yaml` to set your models and their llama-server arguments. The default config includes Qwen3.6-35B-A3B and Gemma 4 31B, both using:
- `--n-gpu-layers 999` — full GPU offload
- `--flash-attn on` — flash attention
- `--batch-size 4096 --ubatch-size 4096` — large batches for fast prompt processing on long contexts
- `--ctx-size 262144` — 256k context window

**4. Start the Docker stack**
```
docker compose up -d --build
```

First startup takes a few minutes — mcp-proxy builds a custom image that pre-installs all MCP packages including the GitHub MCP server (requires Node.js, included in the image).

**5. Start llama-swap**
```
llama-swap --config llama-swap.yaml
```

llama-swap listens on port 8080 and launches llama-server on demand when a model is requested. Models stay loaded until manually unloaded or a different model is requested.

**6. Open LibreChat**

Navigate to `http://localhost:3000` (or `http://<server-ip>:3000` from another device) and register an account. Both models will appear in the model dropdown.

## llama-swap web UI

llama-swap has a built-in UI for monitoring and manually loading/unloading models:
```
http://localhost:8080/ui
```

## Connecting MCP tools from llama.cpp web UI

The llama.cpp built-in web UI also supports MCP directly. Add individual servers:

```
http://<server-ip>:8083/servers/searxng/mcp
http://<server-ip>:8083/servers/time/mcp
http://<server-ip>:8083/servers/github/mcp
# etc.
```

## audio-api (shared STT/TTS)

A single GPU-backed service exposing OpenAI-compatible endpoints — used by LibreChat, signal-bot, and voice-agent. No model duplication; Whisper and Kokoro are loaded once and stay warm.

- `POST /v1/audio/transcriptions` — Whisper (faster-whisper) transcription
- `POST /v1/audio/speech` — Kokoro TTS; supports `stream: true` for sentence-by-sentence chunks
- `GET /v1/voices` — `{voices, default, lang, speed}` — list of installed Kokoro voices plus the current server-side defaults
- `GET /health` — returns 200 only once both models are loaded AND warmed up (CUDA kernels JIT-compiled). `start.sh` polls this before considering the stack ready.

Defaults in `audio-api.env` (**single source of truth** for voice/lang/speed):

```
WHISPER_MODEL=small
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
ONNX_PROVIDER=CUDAExecutionProvider
DEFAULT_VOICE=bm_george
DEFAULT_LANG=b
DEFAULT_SPEED=1.0
```

Callers (voice-agent, calendar-watcher, rss-watcher, etc.) omit `voice`/`lang`/`speed` from their requests so these defaults apply. Pass them explicitly only to override per-request. To change the stack-wide default voice, edit `DEFAULT_VOICE` here and `docker compose restart audio-api` — no other service needs updating. `signal-bot` is the one exception (it reads `TTS_VOICE` from `signal-bot.env` because the uoltz upstream expects it); `librechat.yaml` also pins a UI default under `speechTab.textToSpeech.voice`.

Both models run on the GPU. Post-warmup, first real request latency is ~0.7s. Long sentences are auto-chunked at commas/whitespace before hitting Kokoro's 510-token cap.

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

Available custom skills: arxiv, currency, finance, github, google_maps, hackernews, music_download, patents, pdf, searxng, semantic_scholar, time, weather, wikipedia.

Most are thin MCP-client shims that call mcp-proxy on port 8083. A few do their own thing:

- **github** — calls the GitHub REST API directly (not via mcp-proxy) using `GITHUB_TOKEN` from the environment.
- **music_download** (`/music`) — downloads songs from Shazam or Spotify links as high-quality MP3, trims non-music content from start/end, classifies into a configured directory, and sets ID3 tags including cover art. See setup below.
- **pdf** — calls the pdf-inspector service directly on port 8086.

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

## Notes

- LibreChat chat history is persisted in MongoDB (`mongodb-data` volume) — survives container restarts
- MCP package cache is persisted — tool calls are fast after first use
- SearXNG runs locally — no search queries leave your network
- llama-swap unloads the current model when a different one is requested — only one model in VRAM at a time
- signal-cli-data volume is shared between signal-api (read-write) and signal-bot (read-only)
- mcp-proxy includes Node.js for the GitHub MCP server; all other tools are pure Python via uvx
- audio-api is the single GPU consumer for STT/TTS — signal-bot, LibreChat, and voice-agent all call it over HTTP
- audio-api owns the default voice/lang/speed (`DEFAULT_VOICE` in `audio-api.env`). voice-agent and the watchers omit these fields so the server-side defaults apply; `signal-bot.env` still sets `TTS_VOICE` (uoltz reads it) and `librechat.yaml` pins a UI default. To swap voices stack-wide, change `DEFAULT_VOICE` and restart audio-api
- `./shared/` is bind-mounted (`:ro`) into every watcher (`calendar-watcher`, `tg-watcher`, `oss-watcher`, `rss-watcher`, `location-tracker`) and installed editable — edit `shared/stack_shared/*.py` and `docker compose restart <watcher>` without rebuilding the image
