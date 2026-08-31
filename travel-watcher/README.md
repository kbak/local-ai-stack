# travel-watcher

Turns travel reservation emails into idempotent events in the existing CalDAV
`Travel` calendar. It supports individual flight, train, and bus segments,
hotel arrival markers, a pre-trip `pack & go` event, PDF attachments, and ICS
attachments.

## Behavior

- Each transport segment spans its real departure and arrival time, preserving
  the local UTC offsets supplied by the itinerary.
- Transport titles use `SOURCE → DESTINATION (BOOKING; SERVICE)` and their
  location is the departure airport or station.
- A 30-minute `pack & go` event starts two hours before the first flight in
  each email and has a reminder 15 minutes before it starts.
- Hotel events last 30 minutes. When an arrival near the hotel's city occurs
  around check-in, the event begins 30 minutes after the final such arrival;
  late-night arrivals may therefore place it on the next local day.
- Stable UIDs derived from the source Message-ID and event identity prevent
  duplicates across retries. Messages are archived only after calendar writes
  succeed.
- Low-confidence, irrelevant, malformed, or instruction-bearing messages do
  not write to the calendar and are recorded in `/data/travel.jsonl`.

## Setup

Copy `travel-watcher.env.example` to `travel-watcher.env`, fill in the dedicated
mailbox credentials, then run:

```sh
docker compose -f docker-compose.server.yml up -d --build travel-watcher
```

The service reuses CalDAV and LLM configuration from `.env`. The PDF reader and
travel watcher share a private Docker volume only for the lifetime of PDF
attachment extraction.
