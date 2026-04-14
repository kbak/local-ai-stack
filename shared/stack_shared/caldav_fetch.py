"""Fetch calendar events via the caldav Python library.

Shared by location-tracker and meal-watcher.
Callers pass window/calendar config explicitly so this module has no
dependencies on any service-specific config.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import caldav
import pytz
from icalendar import Calendar

log = logging.getLogger(__name__)


@dataclass
class RawEvent:
    uid: str
    summary: str
    description: str
    location: str       # explicit LOCATION field — may be empty
    start: datetime     # always UTC-normalised
    end: datetime       # always UTC-normalised
    tzid: str           # original TZID string, e.g. "Europe/Warsaw"
    content_hash: str   # SHA-1 of raw iCal component for change detection


def _city_to_tz(city: str) -> str:
    """Best-effort: resolve a city name to an IANA timezone via pytz country/zone lookup."""
    if not city:
        return ""
    # Try geonamescache-style lookup via pytz's known timezones
    city_lower = city.lower().replace(" ", "_")
    for tz in pytz.all_timezones:
        if city_lower in tz.lower():
            return tz
    return ""


def _to_utc(
    dt: datetime | date | None,
    tzid: str,
    local_tz: str = "",
) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if not isinstance(dt, datetime):
        dt = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        # Naive datetime — use TZID, then local_tz fallback, then UTC
        tz_name = tzid or local_tz
        if tz_name:
            try:
                dt = pytz.timezone(tz_name).localize(dt)
            except pytz.UnknownTimeZoneError:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _hash(component) -> str:
    return hashlib.sha1(component.to_ical()).hexdigest()


def _get_cal_name(cal) -> str:
    try:
        return cal.get_display_name() or ""
    except Exception:
        try:
            return cal.name or ""
        except Exception:
            return ""


def fetch_events(
    base_url: str,
    username: str,
    password: str,
    calendar_names: list[str],
    lookback_days: int,
    lookahead_days: int,
    local_tz: str = "",
) -> list[RawEvent]:
    """Return all events across configured calendars within the rolling window."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=lookback_days)
    window_end = now + timedelta(days=lookahead_days)

    client = caldav.DAVClient(url=base_url, username=username, password=password)
    principal = client.principal()
    calendars = principal.calendars()

    if calendar_names:
        names_lower = {n.lower() for n in calendar_names}
        calendars = [c for c in calendars if _get_cal_name(c).lower() in names_lower]
        log.info("Tracking calendars: %s", [_get_cal_name(c) for c in calendars])
    else:
        log.info("Tracking all %d calendars", len(calendars))

    results: list[RawEvent] = []
    seen_uids: set[str] = set()

    for cal in calendars:
        # Primary fetch: server-side date-range search (fast, misses naive-tz events)
        try:
            ranged = cal.search(
                start=window_start,
                end=window_end,
                event=True,
                expand=True,
            )
        except Exception:
            log.exception("Failed to fetch from calendar %s", _get_cal_name(cal))
            ranged = []

        # Secondary fetch: all events without filter, to catch naive-datetime events
        # that the server excludes from date-range queries
        try:
            all_events = cal.events()
        except Exception:
            log.exception("Failed to fetch all events from calendar %s", _get_cal_name(cal))
            all_events = []

        # Merge — deduplicate by raw data identity
        raw_data_seen: set[str] = set()
        combined = []
        for e in list(ranged) + list(all_events):
            key = hashlib.md5(e.data.encode() if isinstance(e.data, str) else e.data).hexdigest()
            if key not in raw_data_seen:
                raw_data_seen.add(key)
                combined.append(e)

        for vevent_obj in combined:
            try:
                ical = Calendar.from_ical(vevent_obj.data)
            except Exception:
                continue

            for component in ical.walk("VEVENT"):
                uid = str(component.get("UID", ""))
                if uid in seen_uids:
                    continue

                summary = str(component.get("SUMMARY", ""))
                description = str(component.get("DESCRIPTION", ""))
                location = str(component.get("LOCATION", ""))

                dtstart = component.get("DTSTART")
                dtend = component.get("DTEND")

                tzid = ""
                if dtstart and hasattr(dtstart, "params"):
                    tzid = dtstart.params.get("TZID", "")

                start_dt = _to_utc(dtstart.dt if dtstart else None, tzid, local_tz)
                end_dt = _to_utc(dtend.dt if dtend else None, tzid, local_tz)

                if end_dt < window_start or start_dt > window_end:
                    continue

                seen_uids.add(uid)
                results.append(RawEvent(
                    uid=uid,
                    summary=summary,
                    description=description,
                    location=location,
                    start=start_dt,
                    end=end_dt,
                    tzid=tzid,
                    content_hash=_hash(component),
                ))

    log.info("Fetched %d events total", len(results))
    return results
