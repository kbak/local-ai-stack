# Local AI Stack

Self-hosted LLM stack with privacy-focused web search and research tools. Runs on a local machine and is accessible from any device on the network.

## Stack

| Service | Port | Description |
|---|---|---|
| llama-swap | 8080 | Model manager — switches between llama-server instances on demand |
| SearXNG | 8081 | Privacy-focused meta search engine |
| mcp-proxy | 8083 | MCP tool server (13 tools via streamable HTTP) |
| MongoDB | — | LibreChat chat history storage |
| LibreChat | 3000 | Web UI, accessible from any device |
| signal-api | 9922 | Signal REST API (bbernhard/signal-cli-rest-api, native mode) |
| signal-bot | — | Signal messenger bot powered by uoltz + local LLM |

## MCP Tools

All tools are exposed via mcp-proxy on port 8083:

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
- **weather** — current weather
- **currency** — exchange rates
- **finance** — stock and financial data (yfinance)

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
Edit `.env` and set strong random values for `JWT_SECRET` and `JWT_REFRESH_SECRET`.

**3. Configure models in `llama-swap.yaml`**

Edit `llama-swap.yaml` to set your models and their llama-server arguments. The default config includes Qwen3.5-35B-A3B and Gemma 4 31B.

**4. Start the Docker stack**
```
docker compose up -d --build
```

First startup takes a few minutes — mcp-proxy builds a custom image that pre-installs all MCP packages.

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
http://<server-ip>:8083/servers/weather/mcp
# etc.
```

## Signal Bot

A Signal messenger bot that routes messages through the local LLM with the same MCP tools available in LibreChat. Built on [uoltz](https://github.com/maciejjedrzejczyk/uoltz), cloned at Docker build time.

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

**3. Build and start**
```
docker compose up -d --build signal-bot
```

### Group chat

The bot responds in groups in two ways:
- **Prefix**: message starts with `BOT_GROUP_PREFIX` (default: `@006`)
- **Mention**: the bot's number is @mentioned in the message

### Custom skills

Skills in `signal-bot-custom-skills/` are mounted into the container and auto-discovered at startup. Each skill is a directory with a `skill.yaml` and a Python file. The built-in `web_search` skill is disabled in favour of the local SearXNG instance.

Available custom skills: arxiv, currency, finance, hackernews, patents, pdf, searxng, semantic_scholar, time, weather, wikipedia.

### Dockerfile patches applied to uoltz

uoltz is cloned from GitHub at build time and patched in place. The patches are not upstreamed.

**1. Disable skill attribution output** (`bot.py`)
The block that prints which skills were used after each response is removed. It was noisy and not useful in a chat context.

**2. Direct signal-cli receive** (`signal_client.py`)
The default receive path calls the signal-api REST endpoint (`GET /v1/receive`). In native mode, signal-api spawns a new `signal-cli` process per request — when the bot polls frequently, concurrent processes fight over the signal-cli config file lock, dropping messages. The patch replaces `receive()` with a direct `subprocess.run(["signal-cli", ...])` call using the shared `signal-cli-data` volume mounted read-only. Poll interval is also raised to 12 s to match the 10 s receive timeout.

**3. Group mention detection** (`bot.py`)
Signal delivers `@mentions` as a U+FFFC (object replacement character) in the message text, not as the literal prefix string. The patch threads the `mentions` array through `parse_messages` and checks whether the bot's own number appears in it. If it does, the leading U+FFFC character is stripped before passing the text to the agent.

**4. Group ID format mismatch** (`signal_client.py`)
Received messages carry `groupId` as the raw `internal_id` (base64, e.g. `9JDGhRIy...=`). The REST API's `/v2/send` endpoint requires the `group.XXX=` prefixed form returned by `/v1/groups/`. The patch adds a `_resolve_group_id()` helper that looks up the correct ID on demand, called automatically in `send()`.

**5. Qwen thinking mode** (`agent.py`)
`/no_think` is prepended to the system prompt to suppress chain-of-thought output tokens from Qwen3 models, keeping responses concise.

## Notes

- Chat history is persisted in a Docker volume — survives container restarts
- MCP package cache is persisted — tool calls are fast after first use
- SearXNG runs locally — no search queries leave your network
- llama-swap unloads the current model when a different one is requested — only one model in VRAM at a time
- signal-cli-data volume is shared between signal-api (read-write) and signal-bot (read-only)
