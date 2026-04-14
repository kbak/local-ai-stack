"""Fetch calendar events via the caldav Python library."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import caldav
import recurring_ical_events
from icalendar import Calendar

from .config import (
    CALDAV_BASE_URL,
    CALDAV_PASSWORD,
    CALDAV_USERNAME,
    CALENDAR_NAMES,
    LOOKBACK_DAYS,
    LOOKAHEAD_DAYS,
)

log = logging.getLogger(__name__)


@dataclass
class RawEvent:
    uid: str
    summary: str
    description: str
    location: str  # explicit LOCATION field — may be empty
    start: datetime  # always UTC-normalised
    end: datetime    # always UTC-normalised
    tzid: str        # original TZID string, e.g. "Europe/Warsaw"
    content_hash: str  # hash of raw ical component for change detection


def _to_utc(dt: datetime | None, tzid: str) -> datetime:
    """Ensure dt is timezone-aware UTC."""
    if dt is None:
        return datetime.now(timezone.utc)
    if hasattr(dt, "date") and not isinstance(dt, datetime):
        # all-day date — treat as midnight UTC
        from datetime import date as _date
        dt = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        # floating time — attach declared TZID or assume UTC
        import pytz
        tz = pytz.timezone(tzid) if tzid else timezone.utc
        dt = tz.localize(dt)
    return dt.astimezone(timezone.utc)


def _hash(component) -> str:
    raw = component.to_ical()
    return hashlib.sha1(raw).hexdigest()


def fetch_events() -> list[RawEvent]:
    """Return all relevant events across configured calendars."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=LOOKBACK_DAYS)
    window_end = now + timedelta(days=LOOKAHEAD_DAYS)

    client = caldav.DAVClient(
        url=CALDAV_BASE_URL,
        username=CALDAV_USERNAME,
        password=CALDAV_PASSWORD,
    )
    principal = client.principal()
    calendars = principal.calendars()

    if CALENDAR_NAMES:
        names_lower = {n.lower() for n in CALENDAR_NAMES}
        calendars = [
            c for c in calendars
            if (c.name or "").lower() in names_lower
        ]
        log.info("Tracking calendars: %s", [c.name for c in calendars])
    else:
        log.info("Tracking all %d calendars", len(calendars))

    results: list[RawEvent] = []

    for cal in calendars:
        try:
            raw_ical_events = cal.search(
                start=window_start,
                end=window_end,
                event=True,
                expand=True,  # expand recurring events
            )
        except Exception:
            log.exception("Failed to fetch from calendar %s", cal.name)
            continue

        for vevent_obj in raw_ical_events:
            try:
                ical = Calendar.from_ical(vevent_obj.data)
            except Exception:
                continue

            for component in ical.walk("VEVENT"):
                uid = str(component.get("UID", ""))
                summary = str(component.get("SUMMARY", ""))
                description = str(component.get("DESCRIPTION", ""))
                location = str(component.get("LOCATION", ""))

                dtstart = component.get("DTSTART")
                dtend = component.get("DTEND")

                tzid = ""
                if dtstart and hasattr(dtstart, "params"):
                    tzid = dtstart.params.get("TZID", "")

                start_dt = _to_utc(dtstart.dt if dtstart else None, tzid)
                end_dt = _to_utc(dtend.dt if dtend else None, tzid)

                # skip events entirely outside our window
                if end_dt < window_start or start_dt > window_end:
                    continue

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
