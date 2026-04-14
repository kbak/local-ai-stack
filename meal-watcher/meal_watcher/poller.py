"""Polling loop: detect new/changed meal events, enrich, deliver, schedule reminders."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from stack_shared.caldav_fetch import fetch_events

import json
import pytz
from stack_shared.mcp_client import call_mcp

from .caldav_update import patch_event
from .classifier import classify
from .config import (
    CALDAV_BASE_URL,
    CALDAV_PASSWORD,
    CALDAV_USERNAME,
    CALENDAR_NAMES,
    LOCAL_TIMEZONE,
    LOCATION_TRACKER_URL,
    LOOKAHEAD_DAYS,
    MCP_AUTH_TOKEN,
)
from .enricher import enrich
from .signal_client import send_message
from .state import EventRecord, State, load, save


def _tz_for_naive_event(event_start_utc: datetime) -> str:
    """Ask location-tracker for city at event time, resolve to IANA tz."""
    try:
        raw = call_mcp(
            LOCATION_TRACKER_URL,
            "get_location_at",
            {"datetime_iso": event_start_utc.isoformat()},
            auth_token=MCP_AUTH_TOKEN,
        )
        data = json.loads(raw)
        city = data.get("city", "")
        if city and city not in ("unknown",):
            # Search pytz for a matching timezone
            city_lower = city.lower().replace(" ", "_")
            for tz in pytz.all_timezones:
                if city_lower in tz.lower():
                    return tz
    except Exception:
        pass
    return LOCAL_TIMEZONE



log = logging.getLogger(__name__)


def poll_once(state: State | None = None) -> State:
    if state is None:
        state = load()

    now = datetime.now(timezone.utc)
    lookback_cutoff = now - timedelta(hours=3)   # catch events that started recently
    lookahead_cutoff = now + timedelta(days=LOOKAHEAD_DAYS)

    try:
        events = fetch_events(
            base_url=CALDAV_BASE_URL,
            username=CALDAV_USERNAME,
            password=CALDAV_PASSWORD,
            calendar_names=CALENDAR_NAMES,
            lookback_days=1,
            lookahead_days=LOOKAHEAD_DAYS,
            local_tz=LOCAL_TIMEZONE,
        )
    except Exception:
        log.exception("CalDAV fetch failed — keeping existing state")
        return state

    seen_uids: set[str] = set()

    for event in events:
        # For naive-datetime events, resolve timezone from location-tracker
        # (for display purposes only — _to_utc already correctly converted the time)
        if not event.tzid:
            tz = _tz_for_naive_event(event.start)
            if tz:
                from dataclasses import replace
                event = replace(event, tzid=tz)

        if event.start > lookahead_cutoff or event.start < lookback_cutoff:
            continue

        seen_uids.add(event.uid)
        existing = state.events.get(event.uid)

        if not existing:
            _process_event(event, state)
            continue

        hash_changed = existing.content_hash != event.content_hash

        if existing.is_meal and not existing.briefing_sent:
            # Meal event where send failed — retry
            log.info("Retrying briefing for uid=%s", event.uid)
            _process_event(event, state)
        elif hash_changed and not existing.briefing_sent:
            # Changed before briefing was sent — re-process
            log.info("Event changed before briefing sent, re-processing uid=%s", event.uid)
            _process_event(event, state)
        elif hash_changed:
            # Briefing already sent, just update the hash
            existing.content_hash = event.content_hash
            save(state)

    # Remove records for events no longer in the calendar
    for uid in list(state.events):
        if uid not in seen_uids:
            log.info("Event uid=%s no longer in calendar, removing", uid)
            del state.events[uid]

    save(state)
    return state


def _process_event(event, state: State) -> None:
    """Classify, enrich, and deliver briefing."""
    log.info("Processing event: '%s' at %s", event.summary, event.start.isoformat())

    result = classify(event)
    if not result.is_meal:
        log.info("Not a meal event: '%s'", event.summary)
        state.events[event.uid] = EventRecord(
            uid=event.uid,
            content_hash=event.content_hash,
            briefing_sent=False,
            briefing_sent_at=None,
        )
        save(state)
        return

    log.info("Meal event confirmed: '%s' → %s in %s", event.summary, result.venue, result.city)

    # Mark as meal before enrichment so retries work if enrichment/send fails
    state.events[event.uid] = EventRecord(
        uid=event.uid,
        content_hash=event.content_hash,
        briefing_sent=False,
        briefing_sent_at=None,
        is_meal=True,
    )
    save(state)

    try:
        briefing, patch_address = enrich(event, result)
    except Exception:
        log.exception("Enrichment failed for '%s'", event.summary)
        return

    # Patch the calendar event: emoji on title, address and maps URL if missing
    from .enricher import _maps_url
    maps_url = _maps_url(result.venue or event.summary, result.city or "")
    patch_event(
        event.uid,
        new_location=patch_address,
        new_url=maps_url if not event.url else None,
    )

    try:
        send_message(briefing)
    except Exception:
        log.exception("Signal send failed for '%s', will retry next poll", event.summary)
        return

    now = datetime.now(timezone.utc)
    state.events[event.uid].briefing_sent = True
    state.events[event.uid].briefing_sent_at = now.isoformat()
    save(state)
