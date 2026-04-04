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

## Notes

- Chat history is persisted in a Docker volume — survives container restarts
- MCP package cache is persisted — tool calls are fast after first use
- SearXNG runs locally — no search queries leave your network
- llama-swap unloads the current model when a different one is requested — only one model in VRAM at a time
