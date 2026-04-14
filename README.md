# Local AI Stack

Self-hosted LLM stack with privacy-focused web search and research tools. Runs on a local machine and is accessible from any device on the network.

## Stack

| Service | Port | Description |
|---|---|---|
| llama-swap | 8080 | Model manager — switches between llama-server instances on demand |
| SearXNG | 8081 | Privacy-focused meta search engine |
| mcp-proxy | 8083 | MCP tool server (16 tools via streamable HTTP) |
| location-tracker | 8084 | City-presence timeline service; exposes `get_location_at` MCP tool |
| meal-watcher | — | Polls calendar for meal events, enriches with rating/menu/weather, delivers briefing via Signal |
| MongoDB | — | LibreChat chat history storage |
| LibreChat | 3000 | Web UI, accessible from any device |
| signal-api | 9922 | Signal REST API (bbernhard/signal-cli-rest-api, native mode) |
| signal-bot | — | Signal messenger bot powered by uoltz + local LLM |

## MCP Tools

All tools are exposed via mcp-proxy on port 8083 and protected by bearer token authentication (`MCP_PROXY_AUTH_TOKEN`). Most are available in both LibreChat and the Signal bot; caldav is LibreChat-only.

- **searxng** — web search (via local SearXNG)
- **fetch** — fetch URL content
- **wikipedia** — Wikipedia search and lookup
- **arxiv** — academic paper search
- **youtube** — YouTube transcript extraction
- **time** — current time and timezone conversion
- **hackernews** — Hacker News top stories
- **pdf** — PDF text extraction
- **semantic-scholar** — academic paper search
- **patents** — patent search
- **weather** — current weather and forecast
- **currency** — exchange rates
- **finance** — stock and financial data (yfinance)
- **github** — read files, search code and repos, browse commits and issues (via official MCP server, requires `GITHUB_TOKEN`)
- **caldav** — calendar access via CalDAV (LibreChat only); requires `CALDAV_BASE_URL`, `CALDAV_USERNAME`, `CALDAV_PASSWORD` in `.env`
- **location-tracker** — `get_location_at(datetime)` — returns city, confidence, and source for any datetime; backed by CalDAV + local LLM + SearXNG. See [`location-tracker/README.md`](location-tracker/README.md).
- **meal-watcher** — no MCP tool; polls calendar, classifies meal events, enriches with rating/menu/weather, delivers briefing via Signal. See [`meal-watcher/README.md`](meal-watcher/README.md).

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
- `CALDAV_BASE_URL`, `CALDAV_USERNAME`, `CALDAV_PASSWORD` — CalDAV server credentials, shared by the caldav MCP tool, location-tracker, and meal-watcher (e.g. Nextcloud: `https://your-nextcloud/remote.php/dav`).
- `MCP_PROXY_AUTH_TOKEN` — bearer token required by all MCP clients to access mcp-proxy and internal MCP servers (location-tracker). Generate with `openssl rand -hex 32`.
- `HOME_CITY` — your home city, used as fallback by location-tracker and as context for travel detection (e.g. `Scottsdale`).
- `CALDAV_CALENDAR_NAMES` — comma-separated calendar names to track for location and meal events (e.g. `Travel`). Leave empty to track all calendars.
- `MEAL_BRIEFING_RECIPIENT` — Signal phone number (international format) that receives meal briefings from meal-watcher.

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
Set `SIGNAL_NUMBER` to your registered number (international format, e.g. `+14155551234`).

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

[Goose](https://github.com/aaif-goose/goose) is a local AI agent for terminal workflows — shell commands, Docker tasks, file operations, and lightweight coding. It runs outside Docker alongside llama-swap and connects to the same models and MCP tools.

### Setup

**1. Download and install**

Download `goose-x86_64-pc-windows-msvc.zip` from the [latest release](https://github.com/aaif-goose/goose/releases/latest), extract, and add to PATH.

**2. Configure**

Goose config lives at `%APPDATA%\Block\goose\config\`. The custom provider for llama-swap is in `custom_providers\custom_llama-swap.json` (created by the wizard or manually).

Key settings in `config.yaml`:
```yaml
GOOSE_PROVIDER: custom_llama-swap
GOOSE_MODEL: qwen           # or gemma4
GOOSE_TOOLSHIM: true        # required for local models — bypasses llama-server's strict JSON Schema validation
GOOSE_TELEMETRY_ENABLED: false
```

Each MCP server is added as a separate `streamable_http` extension pointing at the mcp-proxy per-server paths:
```yaml
extensions:
  finance:
    enabled: true
    type: streamable_http
    name: finance
    uri: http://127.0.0.1:8083/servers/finance/mcp
    headers: {}
    timeout: 60
  # ... one entry per MCP server
```

**Note:** mcp-proxy does not expose an aggregated endpoint — each server must be listed individually.

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

Some MCP servers expose tools with `null` descriptions or `["string", "null"]` union types in their JSON schemas, which cause llama-server to crash when building grammar constraints. `GOOSE_TOOLSHIM: true` bypasses this by handling tool calls in the prompt layer instead. The `wikipedia` extension is disabled in the Goose config due to this issue.

## Notes

- Chat history is persisted in a Docker volume — survives container restarts
- MCP package cache is persisted — tool calls are fast after first use
- SearXNG runs locally — no search queries leave your network
- llama-swap unloads the current model when a different one is requested — only one model in VRAM at a time
- signal-cli-data volume is shared between signal-api (read-write) and signal-bot (read-only)
- mcp-proxy includes Node.js for the GitHub and CalDAV MCP servers; all other tools are pure Python via uvx
- mcp-proxy is built from [PR #187](https://github.com/sparfenyuk/mcp-proxy/pull/187) of the upstream repo which adds bearer token authentication — not yet in an official release
