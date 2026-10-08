# Search and MCP tools

`mcp-proxy` exposes named streamable-HTTP servers on port 8083. All proxy routes,
including SSE and `/status`, require `Authorization: Bearer <MCP_PROXY_AUTH_TOKEN>`.
The host port binds to loopback by default; containers use `http://mcp-proxy:8083`.
Its tool definitions are in `config/mcp-proxy-config.json`.

| Tool group | Interface |
| --- | --- |
| Search, fetch, papers, transcripts, time, weather, currency, finance, GitHub, maps, browser | `http://<server>:8083/servers/<name>/mcp` |
| Location timeline | `http://location-tracker:8084/mcp`, bearer token required |
| PDF inspection | Host port 8086 |
| Memory | `<MEMORY_MCP_URL>/mcp/mcp`, `MEMORY_API_TOKEN` bearer token required |
| Voice cloning | `<AUDIO_API_URL>/mcp/mcp` |

The GitHub adapter restricts commands and REST endpoints to reads. Supply a
read-only token as an additional boundary. Maps needs a Google Places API key.
The [browser agent](browser-agent.md) supports asynchronous tasks and gallery
inspection; use search and fetch for ordinary page retrieval.

The proxy passes provider credentials only to their declared workers: GitHub,
Maps, and browser each run under a separate unprivileged identity. Other workers
share an identity and a writable package cache, but receive no provider secrets.
The broker retains only the capabilities needed to drop worker identities; its
filesystem and tool configuration are read-only.

Memory's REST endpoints use the same `MEMORY_API_TOKEN` as MCP. `/health` remains
public for readiness checks. Agents can add, search, and list memories; deletion
is available only through direct database administration. Qdrant's host port is
loopback-only. Use an SSH tunnel for remote database administration.

## Search

Set `BRAVE_SEARCH_API_KEY` and `SEARXNG_SECRET` in the ignored `.env` file. The
entrypoint renders the tracked SearXNG template at container startup. Never put
credentials directly in `config/searxng-settings.yml`.

```bash
docker compose -f docker-compose.server.yml up -d --force-recreate searxng
```

The search adapter returns structured results and supports result limits, pages,
time ranges, languages, categories, engines, and site restrictions. Search
queries still go to the configured external search providers.
