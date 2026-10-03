"""Polling loop: detect new/changed meal and travel events, enrich, deliver."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import json
import pytz
from stack_shared.caldav_fetch import fetch_events
from stack_shared.caldav_update import patch_event
from stack_shared.mcp_client import call_mcp

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
from .meal_enricher import enrich as meal_enrich, maps_url
from .signal_client import send_message
from .state import EventRecord, State, load, save
from .travel_enricher import enrich as travel_enrich

log = logging.getLogger(__name__)

# Send travel weather notification when event is 20–24h away
_WEATHER_WINDOW_MIN = timedelta(hours=20)
_WEATHER_WINDOW_MAX = timedelta(hours=24)


def _tz_for_naive_event(event_start_utc: datetime) -> str:
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
            city_lower = city.lower().replace(" ", "_")
            for tz in pytz.all_timezones:
                if city_lower in tz.lower():
                    return tz
    except Exception:
        pass
    return LOCAL_TIMEZONE


def poll_once(state: State | None = None) -> State:
    if state is None:
        state = load()

    now = datetime.now(timezone.utc)
    lookback_cutoff = now - timedelta(hours=3)
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

    # Resolve timezones for all events first so connection detection has accurate times
    resolved_events = []
    for event in events:
        if not event.tzid:
            tz = _tz_for_naive_event(event.start)
            if tz:
                from dataclasses import replace
                event = replace(event, tzid=tz)
        resolved_events.append(event)

    for event in resolved_events:
        if event.start > lookahead_cutoff or event.start < lookback_cutoff:
            continue

        seen_uids.add(event.uid)
        existing = state.events.get(event.uid)

        if not existing:
            _process_event(event, state, now, resolved_events)
            continue

        hash_changed = existing.content_hash != event.content_hash

        if existing.event_type in ("meal", "travel") and not existing.briefing_sent:
            log.info("Retrying briefing for uid=%s", event.uid)
            _process_event(event, state, now, resolved_events)
        elif hash_changed and not existing.briefing_sent:
            log.info("Event changed before briefing sent, re-processing uid=%s", event.uid)
            _process_event(event, state, now, resolved_events)
        elif hash_changed:
            existing.content_hash = event.content_hash
            save(state)
        elif existing.event_type == "travel" and not existing.weather_sent:
            # Check if we're in the 24h window for the weather notification
            _maybe_send_travel_weather(event, existing, state, now)

    for uid in list(state.events):
        if uid not in seen_uids:
            log.info("Event uid=%s no longer in calendar, removing", uid)
            del state.events[uid]

    save(state)
    return state


_FLIGHT_PATTERN = re.compile(
    r"(\u2192|->|\bflight\b|\bdepart\b|\bfly\b)",
    re.IGNORECASE,
)
_AIRPORT_CODE = re.compile(r"\b[A-Z]{3}\b")


def _looks_like_flight(summary: str) -> bool:
    return bool(_FLIGHT_PATTERN.search(summary)) or len(_AIRPORT_CODE.findall(summary)) >= 2


def _is_connection(event, all_events: list) -> bool:
    """Return True if another flight departs within 6h of this event ending."""
    window = timedelta(hours=6)
    for other in all_events:
        if other.uid == event.uid:
            continue
        if event.end <= other.start <= event.end + window:
            if _looks_like_flight(other.summary):
                return True
    return False


def _process_event(event, state: State, now: datetime, all_events: list) -> None:
    log.info("Processing event: '%s' at %s", event.summary, event.start.isoformat())

    result = classify(event)

    if result.event_type == "ignored":
        log.info("Ignored event: '%s'", event.summary)
        state.events[event.uid] = EventRecord(
            uid=event.uid,
            content_hash=event.content_hash,
            event_type="ignored",
            briefing_sent=False,
            briefing_sent_at=None,
        )
        save(state)
        return

    if result.is_meal:
        _process_meal(event, result, state, now)
    elif result.is_travel:
        _process_travel(event, result, state, now, all_events)


def _process_meal(event, result, state: State, now: datetime) -> None:
    log.info("Meal event: '%s' → %s in %s", event.summary, result.venue, result.city)

    state.events[event.uid] = EventRecord(
        uid=event.uid,
        content_hash=event.content_hash,
        event_type="meal",
        briefing_sent=False,
        briefing_sent_at=None,
    )
    save(state)

    try:
        briefing, patch_address = meal_enrich(event, result)
    except Exception:
        log.exception("Meal enrichment failed for '%s'", event.summary)
        return

    venue = result.venue or event.summary
    city = result.city or ""
    # Prefer the precise LOCATION (existing or just-patched) for the Maps pin;
    # fall back to "venue city". patch_event ignores new_url when URL is set.
    map_query = patch_address or event.location.strip() or f"{venue} {city}"
    try:
        patch_event(
            event.uid,
            caldav_base_url=CALDAV_BASE_URL,
            caldav_username=CALDAV_USERNAME,
            caldav_password=CALDAV_PASSWORD,
            new_summary_prefix="🍽",
            new_location=patch_address,
            new_url=maps_url(map_query),
        )
    except Exception:
        log.warning("CalDAV patch failed for '%s', continuing", event.summary)

    try:
        send_message(briefing)
    except Exception:
        log.exception("Signal send failed for '%s', will retry next poll", event.summary)
        return

    state.events[event.uid].briefing_sent = True
    state.events[event.uid].briefing_sent_at = now.isoformat()
    save(state)


def _process_travel(event, result, state: State, now: datetime, all_events: list) -> None:
    city = result.city

    # Skip connections — another flight departs within 6h of this one landing
    if _is_connection(event, all_events):
        log.info("Skipping connection at '%s' (another flight within 6h)", city)
        state.events[event.uid] = EventRecord(
            uid=event.uid,
            content_hash=event.content_hash,
            event_type="travel",
            briefing_sent=True,   # mark sent so we don't retry
            briefing_sent_at=now.isoformat(),
            weather_sent=True,
        )
        save(state)
        return

    # Skip if city hasn't changed from last anchor
    if city and city.lower() == (state.last_anchor_city or "").lower():
        log.info("Travel to '%s' but same as last anchor city, skipping", city)
        state.events[event.uid] = EventRecord(
            uid=event.uid,
            content_hash=event.content_hash,
            event_type="travel",
            briefing_sent=True,
            briefing_sent_at=now.isoformat(),
            weather_sent=True,
        )
        save(state)
        return

    log.info("Travel anchor: '%s' → %s", event.summary, city)

    state.events[event.uid] = EventRecord(
        uid=event.uid,
        content_hash=event.content_hash,
        event_type="travel",
        briefing_sent=False,
        briefing_sent_at=None,
        weather_sent=False,
    )
    save(state)

    # Patch calendar event with emoji
    try:
        patch_event(
            event.uid,
            caldav_base_url=CALDAV_BASE_URL,
            caldav_username=CALDAV_USERNAME,
            caldav_password=CALDAV_PASSWORD,
            new_summary_prefix="✈️",
        )
    except Exception:
        log.warning("CalDAV patch failed for travel '%s', continuing", event.summary)

    # Update last anchor city
    if city:
        state.last_anchor_city = city
        save(state)

    # Send weather now if within 24h window, otherwise wait for next poll cycle
    time_until = event.start - now
    if _WEATHER_WINDOW_MIN <= time_until <= _WEATHER_WINDOW_MAX:
        _send_travel_weather(event, result, state, now)
    elif time_until < _WEATHER_WINDOW_MIN:
        # Event is imminent / already started — send immediately
        _send_travel_weather(event, result, state, now)
    else:
        log.info("Travel anchor '%s' registered, weather will be sent 24h before departure", city)
        state.events[event.uid].briefing_sent = True
        state.events[event.uid].briefing_sent_at = now.isoformat()
        save(state)


def _maybe_send_travel_weather(event, record: EventRecord, state: State, now: datetime) -> None:
    time_until = event.start - now
    if time_until <= _WEATHER_WINDOW_MAX:
        _send_travel_weather(event, None, state, now, record=record)


def _send_travel_weather(event, result, state: State, now: datetime, *, record: EventRecord | None = None) -> None:
    if record is None:
        record = state.events.get(event.uid)
    if record is None:
        return

    # Re-classify if we don't have a result (called from _maybe_send_travel_weather)
    if result is None:
        result = classify(event)

    try:
        briefing = travel_enrich(event, result)
    except Exception:
        log.exception("Travel enrichment failed for '%s'", event.summary)
        return

    try:
        send_message(briefing)
    except Exception:
        log.exception("Signal send failed for travel '%s', will retry", event.summary)
        return

    record.weather_sent = True
    record.weather_sent_at = now.isoformat()
    save(state)
