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
| calendar-watcher | — | Polls calendar for meal and travel events; enriches with rating/menu/weather/maps; delivers briefings via Signal |
| tg-watcher | — | Listens to a Telegram group as your user account; sends a daily LLM-generated brief via Signal |
| MongoDB | — | LibreChat chat history storage |
| LibreChat | 3000 | Web UI, accessible from any device |
| signal-api | 9922 | Signal REST API (bbernhard/signal-cli-rest-api, native mode) |
| signal-bot | — | Signal messenger bot powered by uoltz + local LLM |

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
- `GOOGLE_PLACES_API_KEY` — Google Places API (New) key for venue ratings and addresses in meal briefings.

**3. Configure models in `llama-swap.yaml`**

Edit `llama-swap.yaml` to set your models and their llama-server arguments. The default config includes Qwen3.5-35B-A3B and Gemma 4 31B, both using:
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

Skills in `signal-bot-custom-skills/` are mounted into the container and auto-discovered at startup. Each skill is a directory with a `skill.yaml` and a Python file. The built-in `web_search` skill is disabled in favour of the local SearXNG instance.

Available custom skills: arxiv, currency, finance, github, hackernews, patents, pdf, searxng, semantic_scholar, time, weather, wikipedia.

The **github** skill calls the GitHub REST API directly (not via mcp-proxy) using `GITHUB_TOKEN` from the environment.

### Patches applied to uoltz

All patches are maintained in the [kbak/uoltz](https://github.com/kbak/uoltz) fork and applied directly to the source. See the fork's README for full details.

**1. Disable skill attribution output** (`bot.py`)
The block that prints which skills were used after each response is removed. It was noisy and not useful in a chat context.

**2. Message acknowledgement via emoji reaction** (`signal_client.py`, `bot.py`)
Instead of sending a `⏳ Got it, working on it...` text message as an acknowledgement, the bot now reacts to the incoming message with a 🤖 emoji via the signal-api reactions endpoint. This keeps the chat clean and provides immediate feedback without adding a noisy message to the thread. The `react()` method is added to `SignalClient`; `bot.py` is patched to call it instead of `send()` for acks, passing the original message's sender and timestamp.

**3. Per-sender conversation history** (`agent.py`, `bot.py`)
The original uoltz code maintains a single shared `Agent` instance, meaning all conversations share the same history and context window — users' messages get mixed together. The patch replaces the single `_agent` global with a `dict[str, Agent]` keyed by conversation ID: the sender's phone number for direct messages, or the group ID for group chats. Each conversation gets its own isolated history. Model or context window changes (via `/model`, `/context`) clear all per-sender agents so they are lazily recreated with the new settings on the next message.

**4. Language-aware responses** (`agent.py`)
The system prompt is extended with an instruction to always respond in the same language the user is currently writing in. This is particularly useful in multilingual households or groups.

**5. Group mention detection** (`bot.py`)
Signal delivers `@mentions` as a U+FFFC (object replacement character) in the message text, not as the literal prefix string. The patch threads the `mentions` array through `parse_messages` and checks whether the bot's own number appears in it. If it does, the leading U+FFFC character is stripped before passing the text to the agent.

**6. Group ID format mismatch** (`signal_client.py`)
Received messages carry `groupId` as the raw `internal_id` (base64, e.g. `9JDGhRIy...=`). The REST API's `/v2/send` endpoint requires the `group.XXX=` prefixed form returned by `/v1/groups/`. The patch adds a `_resolve_group_id()` helper that looks up the correct ID on demand, called automatically in `send()`.

**7. Qwen thinking mode** (`agent.py`)
`/no_think` is prepended to the system prompt to suppress chain-of-thought output tokens from Qwen3 models, keeping responses concise.

## Goose CLI Agent

[Goose](https://github.com/block/goose) is a local AI agent for terminal workflows — shell commands, Docker tasks, file operations, and lightweight coding. It runs outside Docker alongside llama-swap and connects to the same models and MCP tools.

### Setup

**1. Download and install**

Download `goose-x86_64-pc-windows-msvc.zip` from the [latest release](https://github.com/block/goose/releases/latest), extract, and add to PATH.

**2. Configure**

Goose config lives at `%APPDATA%\Block\goose\config\`. The custom provider for llama-swap is in `custom_providers\custom_llama-swap.json` (created by the wizard or manually).

Key settings in `config.yaml`:
```yaml
GOOSE_PROVIDER: custom_llama-swap
GOOSE_MODEL: qwen           # or gemma4
GOOSE_TOOLSHIM: true        # required for local models — bypasses llama-server's strict JSON Schema validation
GOOSE_TELEMETRY_ENABLED: false
```

MCP tools are added as `streamable_http` extensions (except pdf which runs as a local stdio server):
```yaml
extensions:
  searxng:
    enabled: true
    type: streamable_http
    name: searxng
    uri: http://127.0.0.1:8083/servers/searxng/mcp
    headers: {}
    timeout: 60
  # ... one entry per MCP server
  pdf:
    enabled: true
    type: streamable_http
    name: pdf
    uri: http://127.0.0.1:8086/mcp
    headers: {}
    timeout: 120
```

**Note:** mcp-proxy does not expose an aggregated endpoint — each server must be listed individually. `wikipedia` is disabled due to JSON schema incompatibilities with local models (`GOOSE_TOOLSHIM: true` mitigates most but not all).

**3. Start a session**
```
goose session
```

### Thinking mode

Qwen3 models support toggling chain-of-thought reasoning mid-session:
- `/think` — enable thinking (default, ~20s per response for 35B model)
- `/no_think` — disable thinking for fast responses (~1–2s)

The toggle persists for the rest of the session.

### MCP tool compatibility

Some MCP servers expose tools with `null` descriptions or `["string", "null"]` union types in their JSON schemas, which cause llama-server to crash when building grammar constraints. `GOOSE_TOOLSHIM: true` bypasses this by handling tool calls in the prompt layer instead.

## calendar-watcher

Polls CalDAV calendars and sends Signal briefings for:

- **Meal events** — detected restaurant bookings get enriched with Google Places rating, menu URL, weather, and a Google Maps link. The calendar event is patched with a 🍽 emoji prefix, the Places-resolved address (if the location field was empty or vague), and a Maps URL.
- **Travel anchors** — first flight or arrival event to a new city gets a weather forecast sent 24h before departure via Signal. The calendar event is patched with a ✈️ emoji prefix. Connecting flights (another flight departing within 6h) are skipped.

Requires `CALDAV_BASE_URL`, `CALDAV_USERNAME`, `CALDAV_PASSWORD`, `CALDAV_CALENDAR_NAMES`, `GOOGLE_PLACES_API_KEY` in `.env`, and `SIGNAL_NUMBER`, `BRIEFING_RECIPIENT` in `signal-bot.env`.

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

## Notes

- LibreChat chat history is persisted in MongoDB (`mongodb-data` volume) — survives container restarts
- MCP package cache is persisted — tool calls are fast after first use
- SearXNG runs locally — no search queries leave your network
- llama-swap unloads the current model when a different one is requested — only one model in VRAM at a time
- signal-cli-data volume is shared between signal-api (read-write) and signal-bot (read-only)
- mcp-proxy includes Node.js for the GitHub MCP server; all other tools are pure Python via uvx
