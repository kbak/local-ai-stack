"""Background polling loop: fetch events, parse incrementally, update state."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .caldav_fetch import fetch_events
from .parser import parse_event_location
from .state import RawAnchor, State, load, save
from .timeline import build_spans

log = logging.getLogger(__name__)


def _make_source(summary: str, location: str, start_iso: str, confidence: str) -> str:
    if confidence == "explicit":
        return f"{summary} @ {location} (from {start_iso[:10]})"
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

        # Fast path: explicit LOCATION field
        if event.location.strip():
            city = event.location.strip()
            confidence = "explicit"
            source = _make_source(event.summary, city, start_iso, confidence)
            log.info("Explicit location for '%s': %s", event.summary, city)
        else:
            # LLM path
            city, confidence = parse_event_location(
                summary=event.summary,
                description=event.description,
                start_iso=start_iso,
                end_iso=end_iso,
                tzid=event.tzid,
            )
            if city:
                source = _make_source(event.summary, city, start_iso, confidence or "low")
                log.info("LLM parsed '%s' → %s (%s)", event.summary, city, confidence)
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
