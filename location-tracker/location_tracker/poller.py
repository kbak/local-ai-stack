"""Background polling loop: fetch events, parse incrementally, update state."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from datetime import timedelta

from .caldav_fetch import fetch_events
from .parser import parse_event_location
from .state import RawAnchor, State, load, save
from .timeline import build_spans

# Events shorter than this cannot be travel — they are reminders or planning notes.
MIN_TRAVEL_DURATION = timedelta(hours=1)

log = logging.getLogger(__name__)


def _make_source(summary: str, location: str, start_iso: str, confidence: str) -> str:
    return f"{summary} (from {start_iso[:10]})"


def poll_once(state: State | None = None) -> State:
    if state is None:
        state = load()

    try:
        events = fetch_events()
    except Exception:
        log.exception("CalDAV fetch failed — keeping existing state")
        return state

    seen_uids: set[str] = set()

    for event in events:
        seen_uids.add(event.uid)
        existing = state.anchors.get(event.uid)

        # Skip if unchanged
        if existing and existing.content_hash == event.content_hash:
            continue

        start_iso = event.start.isoformat()
        end_iso = event.end.isoformat()

        # Short events are reminders or planning notes — skip LLM entirely.
        if (event.end - event.start) < MIN_TRAVEL_DURATION:
            log.debug("Skipping short event '%s' (%s)", event.summary, event.end - event.start)
            state.anchors[event.uid] = RawAnchor(
                uid=event.uid,
                city=None,
                confidence=None,
                source=event.summary,
                start_utc=start_iso,
                end_utc=end_iso,
                content_hash=event.content_hash,
            )
            continue

        # Always run LLM to determine if this is genuine travel.
        # The explicit LOCATION field (if any) is passed as a hint but does not bypass classification —
        # a concert or dinner at a local venue should not be treated as a location change.
        city, confidence = parse_event_location(
            summary=event.summary,
            description=event.description,
            location_hint=event.location.strip(),
            start_iso=start_iso,
            end_iso=end_iso,
            tzid=event.tzid,
        )
        if city:
            source = _make_source(event.summary, city, start_iso, confidence or "low")
            log.info("Parsed '%s' → %s (%s)", event.summary, city, confidence)
        else:
            source = event.summary
            log.debug("No travel signal in '%s'", event.summary)

        state.anchors[event.uid] = RawAnchor(
            uid=event.uid,
            city=city,
            confidence=confidence,
            source=source,
            start_utc=start_iso,
            end_utc=end_iso,
            content_hash=event.content_hash,
        )

    # Remove UIDs no longer in the calendar, but only if they're in the future.
    # Past anchors are kept even if the calendar event was deleted — the trip already happened.
    now = datetime.now(timezone.utc)
    for uid in list(state.anchors):
        if uid not in seen_uids:
            anchor = state.anchors[uid]
            end_utc = datetime.fromisoformat(anchor.end_utc)
            if end_utc.tzinfo is None:
                end_utc = end_utc.replace(tzinfo=timezone.utc)
            if end_utc > now:
                log.info("Removing cancelled future event uid=%s (%s)", uid, anchor.source)
                del state.anchors[uid]
            else:
                log.debug("Retaining past event uid=%s (%s) — deleted from calendar but already occurred", uid, anchor.source)

    # Recompute derived spans from all anchors
    state.spans = build_spans(state.anchors)

    save(state)
    return state
