# Search, MCP tools, and editor integration

`mcp-proxy` exposes named streamable-HTTP servers on port 8083. The proxy itself
has no authentication; restrict it to trusted clients. Its tool definitions are
in `mcp-proxy-config.json`.

| Tool group | Interface |
| --- | --- |
| Search, fetch, papers, transcripts, time, weather, currency, finance, GitHub, maps, browser | `http://<server>:8083/servers/<name>/mcp` |
| Location timeline | `http://location-tracker:8084/mcp`, bearer token required |
| PDF inspection | Host port 8086 |
| Memory | `<MEMORY_MCP_URL>/mcp/mcp` |
| Voice cloning | `<AUDIO_API_URL>/mcp/mcp` |

The GitHub adapter restricts commands and REST endpoints to reads. Supply a
read-only token as an additional boundary. Maps needs a Google Places API key.
The [browser agent](browser-agent.md) supports asynchronous tasks and gallery
inspection; use search and fetch for ordinary page retrieval.

## Search

Set `BRAVE_SEARCH_API_KEY` and `SEARXNG_SECRET` in the ignored `.env` file. The
entrypoint renders the tracked SearXNG template at container startup. Never put
credentials directly in `searxng-settings.yml`.

```bash
docker compose -f docker-compose.server.yml up -d --force-recreate searxng
```

The search adapter returns structured results and supports result limits, pages,
time ranges, languages, categories, engines, and site restrictions. Search
queries still go to the configured external search providers.

## Continue

Configure Continue to use the OpenAI-compatible llama-swap endpoint. Model IDs
must match `llama-swap.yaml`. For example:

```yaml
name: Local Stack
version: 1.0.0
schema: v1
models:
  - name: Chat
    provider: openai
    model: qwen3.8-27B-FP8
    apiBase: http://127.0.0.1:8080/v1
    apiKey: dummy
    roles: [chat, edit, apply]
  - name: Autocomplete
    provider: openai
    model: qwen-coder-7B
    apiBase: http://127.0.0.1:8080/v1
    apiKey: dummy
    roles: [autocomplete]
```

The examples in `.continue/mcpServers/` connect to local MCP endpoints. Adjust
addresses in your private editor configuration when the services run remotely.
