# location-tracker

Background service that builds and maintains a city-presence timeline from CalDAV calendar events, and exposes a single MCP tool — `get_location_at(datetime)` — that any agent or service in the stack can call.

## How it works

1. **Fetches** calendar events from CalDAV (via Python `caldav` lib) over a rolling window: 30 days back + 90 days ahead.
2. **Parses** each event for travel signals:
   - Events with an explicit `LOCATION` field are used directly — no inference needed.
   - Everything else is sent to the local LLM (via llama-swap) with a `search` tool backed by SearXNG. The LLM extracts a city and confidence level, or returns `null` if the event is not travel-related.
3. **Builds** a timeline of `{city, confidence, start, end}` anchors sorted chronologically. Gaps between anchors inherit the most recent known city. Before and after all anchors, falls back to `HOME_CITY` (or `unknown` if unset).
4. **Persists** state as JSON keyed by event UID + content hash — only changed or new events are re-parsed on each poll.
5. **Exposes** an MCP server on port 8084 with one tool: `get_location_at`.

## MCP tool

```
get_location_at(datetime_iso: str) → {
    city: str,
    confidence: "high" | "medium" | "low" | "explicit" | "fallback",
    source: str
}
```

- `explicit` — taken from the event's `LOCATION` field
- `high` — LLM identified a clear travel destination (flight arrival, hotel check-in)
- `medium` — "driving to X", "going to X", named hotel with city
- `low` — vague signal, LLM best guess
- `fallback` — no data; returns `HOME_CITY` or `unknown`

## Configuration

Set in the stack's `.env`:

| Variable | Default | Description |
|---|---|---|
| `HOME_CITY` | _(empty)_ | Fallback city when no travel data is available. Leave blank to return `unknown`. |
| `CALDAV_CALENDAR_NAMES` | _(all calendars)_ | Comma-separated calendar names to track (e.g. `Travel`). Empty = track all. |
| `POLL_INTERVAL_MINUTES` | `5` | How often to poll CalDAV. |
| `LOOKBACK_DAYS` | `30` | How far back to scan for past travel anchors. |
| `LOOKAHEAD_DAYS` | `90` | How far ahead to scan for future events. |
| `INFERENCE_BASE_URL` | `http://host.docker.internal:8080/v1` | OpenAI-compatible LLM endpoint. |
| `INFERENCE_MODEL` | `qwen` | Model name to use for parsing. |
| `SEARXNG_URL` | `http://searxng:8080` | SearXNG instance for the LLM's search tool. |

CalDAV credentials (`CALDAV_BASE_URL`, `CALDAV_USERNAME`, `CALDAV_PASSWORD`) are shared with the rest of the stack.

## Dependencies

Locked in `uv.lock`. To update:

```
uv lock
```

Then rebuild the Docker image.

## Timeline semantics

- **During an event's span**: city comes from that event.
- **Between two anchors**: city from the most recent prior anchor (you're still in the last known place).
- **Before first anchor / after last anchor**: `HOME_CITY` or `unknown`.
- **In transit**: for the duration of a travel event (e.g. a flight), the *destination* city is used starting from `event.start`. There is no "in transit" state — the assumption is that from the moment you leave, the destination is your effective location.
