from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

import caldav
from icalendar import Alarm, Calendar, Event

from .config import CALDAV_BASE_URL, CALDAV_PASSWORD, CALDAV_USERNAME, CALENDAR_NAME
from .models import Hotel, Itinerary, Transport

log = logging.getLogger(__name__)


def _uid(kind: str, identity: str) -> str:
    # Intentionally independent of Message-ID: forwarding the same reservation twice
    # must converge on the same calendar objects.
    digest = hashlib.sha256(f"{kind}\0{identity}".encode()).hexdigest()
    return f"travel-watcher-{digest[:40]}@local-ai-stack"


def _calendar():
    principal = caldav.DAVClient(
        url=CALDAV_BASE_URL, username=CALDAV_USERNAME, password=CALDAV_PASSWORD,
    ).principal()
    for calendar in principal.calendars():
        try:
            name = calendar.get_display_name() or ""
        except Exception:
            name = getattr(calendar, "name", "") or ""
        if name.casefold() == CALENDAR_NAME.casefold():
            return calendar
    raise RuntimeError(f"CalDAV calendar {CALENDAR_NAME!r} not found")


def _exists(calendar, uid: str) -> bool:
    return bool(calendar.search(uid=uid, event=True))


def _save(calendar, uid: str, summary: str, start: datetime, end: datetime, location: str = "", reminder: bool = False) -> bool:
    if _exists(calendar, uid):
        return False
    cal = Calendar()
    cal.add("prodid", "-//local-ai-stack//travel-watcher//EN")
    cal.add("version", "2.0")
    event = Event()
    event.add("uid", uid)
    event.add("summary", summary)
    event.add("dtstart", start)
    event.add("dtend", end)
    event.add("dtstamp", datetime.now(timezone.utc))
    if location:
        event.add("location", location)
    if reminder:
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", summary)
        alarm.add("trigger", timedelta(minutes=-15))
        event.add_component(alarm)
    cal.add_component(event)
    calendar.save_event(cal.to_ical())
    return True


def _transport_title(item: Transport) -> str:
    source = item.source_code or item.source_name
    destination = item.destination_code or item.destination_name
    details = [*item.booking_codes]
    if item.service_number and item.service_number not in details:
        details.append(item.service_number)
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"{source} → {destination}{suffix}"


def _hotel_start(hotel: Hotel, transports: list[Transport]) -> datetime:
    # The final arrival from 18h before check-in through 12h after it handles late-night
    # arrivals crossing the destination's local midnight without attaching unrelated legs.
    candidates = [
        leg for leg in transports
        if hotel.check_in - timedelta(hours=18) <= leg.arrival <= hotel.check_in + timedelta(hours=12)
        and _near_destination(hotel, leg)
    ]
    if candidates:
        return max(leg.arrival for leg in candidates) + timedelta(minutes=30)
    return hotel.check_in


def _near_destination(hotel: Hotel, leg: Transport) -> bool:
    haystack = f"{leg.destination_code} {leg.destination_name}".casefold()
    tokens = [token for token in hotel.city.casefold().replace(",", " ").split() if len(token) >= 3]
    return bool(tokens) and any(token in haystack for token in tokens)


def create_events(itinerary: Itinerary) -> int:
    calendar = _calendar()
    created = 0
    transports = sorted(itinerary.transports, key=lambda item: item.departure)
    for item in transports:
        identity = f"{item.mode}|{item.departure.isoformat()}|{item.arrival.isoformat()}|{item.service_number}"
        created += _save(calendar, _uid("transport", identity), _transport_title(item),
                         item.departure, item.arrival, item.source_location)
    flights = [item for item in transports if item.mode == "flight"]
    if flights:
        first = flights[0]
        start = first.departure - timedelta(hours=2)
        created += _save(calendar, _uid("pack", first.departure.isoformat()), "pack & go",
                         start, start + timedelta(minutes=30), first.source_location, reminder=True)
    for hotel in itinerary.hotels:
        start = _hotel_start(hotel, transports)
        identity = f"{hotel.name}|{hotel.location}|{hotel.check_in.isoformat()}"
        created += _save(calendar, _uid("hotel", identity), hotel.name,
                         start, start + timedelta(minutes=30), hotel.location)
    return created
