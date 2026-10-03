# Scheduled watchers

Watchers use shared LLM and Signal helpers. They select a ready non-coder chat
model through llama-swap instead of loading a different model for each job.
Recipients and integration credentials are local configuration.

| Service | Purpose | Configuration |
| --- | --- | --- |
| calendar-watcher | Meal/travel enrichment and Signal reminders | `.env`, `signal-bot.env` |
| location-tracker | Calendar-derived city timeline | [.env.example](../.env.example), [service guide](../location-tracker/README.md) |
| tg-watcher | Daily Telegram group summary | `tg-watcher.env`, `signal-bot.env` |
| rss-watcher | Twice-daily news and optional weekly blogs | `rss-watcher.env`, `signal-bot.env` |
| oss-watcher | GitHub/Discord project summary | `oss-watcher.env`, `signal-bot.env` |
| receipt-watcher | Email receipts to Sheets | [service guide](../receipt-watcher/README.md) |
| travel-watcher | Travel emails to calendar events | [service guide](../travel-watcher/README.md) |
| plc-watcher | Historical-region weather briefing | `plc-watcher.env`, `signal-bot.env` |

Copy each required `*.env.example` to its runtime name. Start the chosen service
with its dependencies:

```bash
docker compose -f docker-compose.server.yml up -d --build rss-watcher
```

## Calendar and location

Configure CalDAV credentials, calendar names, home city, and `LOCAL_TIMEZONE`.
The calendar watcher enriches restaurant bookings with place details and travel
anchors with weather. It updates calendar events as well as sending reminders.
Google Places enrichment needs `GOOGLE_MAPS_API_KEY`.

## Telegram

Use API credentials from `my.telegram.org` and the target group ID. Set
`TG_API_ID`, `TG_API_HASH`, `TG_PHONE`, and `TG_GROUP`, then complete the initial
interactive login:

```bash
docker compose -f docker-compose.server.yml run --rm -it tg-watcher python auth.py
```

The user session and collected messages persist in the watcher volume. Schedule
fields in its example file use UTC. The service reads messages as the configured
user account; it does not add a bot to the group.

## RSS and blogs

`RSS_FEEDS` maps category names to feed URL lists. News summaries run at 00:05 and
12:05 UTC and cover the preceding 12 hours. Each category is summarized
independently. Set the sources and optional voice delivery in `rss-watcher.env`.

For the weekly digest, copy `rss-watcher/blog-sources.example.json` to the ignored
`rss-watcher/blog-sources.json`, replace its examples, and set `BLOG_SOURCES_FILE`.
The digest runs Tuesday at 10:00 in `BLOG_TIMEZONE` (UTC by default).

The blog job accepts feeds and dated HTML articles. It filters to the preceding
seven days, rejects future/undated entries, and deduplicates within each run.
`BLOG_RECIPIENT` defaults to `BRIEFING_RECIPIENT`; group recipients are rejected.
Blog delivery is text-only. A manual rerun can repeat entries, and a restart does
not replay a missed scheduled run.
