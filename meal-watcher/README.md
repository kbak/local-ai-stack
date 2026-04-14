# meal-watcher

Background service that polls CalDAV for new or changed calendar events, classifies them as meal/restaurant bookings using an LLM, enriches confirmed meal events with rating, full menu, and weather, and delivers a briefing via Signal.

## How it works

1. **Polls** CalDAV every `POLL_INTERVAL_MINUTES` for events starting within the next `LOOKAHEAD_DAYS`.
2. **Classifies** each new or changed event using the LLM with web search. Only proceeds if the event is confidently a named restaurant or dining venue booking. Personal notes, vague titles, and non-venue events are discarded.
3. **Enriches** confirmed meal events via a single LLM agent call with tools: `search`, `fetch`, `read_pdf`, `get_weather`, `get_location_at`. The agent:
   - Looks up the restaurant's rating, cuisine, price range, and accolades
   - Extracts the complete menu (follows sub-menu links, falls back to search snippets for JS-rendered sites, uses `read_pdf` for PDF menus)
   - Fetches weather at the event city and time
4. **Delivers** the briefing immediately via Signal to `MEAL_BRIEFING_RECIPIENT`.
5. **Tracks** processed events by UID + content hash in `seen_events.json`. Re-processes if an event changes before the briefing was sent; otherwise skips.

## Classification behaviour

The classifier is conservative — false positives (briefing for a non-restaurant) are worse than false negatives (missing a restaurant). It will discard:
- Vague titles: "dinner", "lunch with Sarah", "drinks"
- Personal notes mentioning food: "let's grab wine at the hotel"
- Non-venue events with incidental food mentions
- Events where the description contradicts a restaurant reading of the title

## Configuration

All set in the stack's `.env`:

| Variable | Required | Default | Description |
|---|---|---|---|
| `MEAL_BRIEFING_RECIPIENT` | Yes | — | Signal number to receive briefings (international format, e.g. `+14155551234`) |
| `CALDAV_BASE_URL` | Yes | — | CalDAV server URL (shared with location-tracker) |
| `CALDAV_USERNAME` | Yes | — | CalDAV username |
| `CALDAV_PASSWORD` | Yes | — | CalDAV password |
| `CALDAV_CALENDAR_NAMES` | No | all calendars | Comma-separated calendar names to watch |
| `POLL_INTERVAL_MINUTES` | No | `5` | Poll frequency |
| `LOOKAHEAD_DAYS` | No | `90` | How far ahead to scan for events |
| `HOME_CITY` | No | — | Fallback city for location resolution |
| `SIGNAL_NUMBER` | Yes | — | Bot's Signal number (from `signal-bot.env`) |
| `SIGNAL_API_URL` | No | `http://signal-api:8080` | signal-api endpoint |
| `MCP_PROXY_AUTH_TOKEN` | No | — | Bearer token for mcp-proxy and location-tracker |

## Dependencies

- **location-tracker** — called via MCP to resolve the user's city at event time
- **mcp-proxy** — provides `weather`, `fetch`, and `pdf` tools to the enrichment agent
- **searxng** — web search for classification and enrichment
- **signal-api** — Signal message delivery

## Shared library

Common CalDAV fetching and MCP client logic lives in `../shared/stack_shared/` and is installed as a local package at build time.
