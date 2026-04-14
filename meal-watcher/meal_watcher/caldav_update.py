"""Patch a CalDAV event's SUMMARY, LOCATION, and URL fields in-place."""

from __future__ import annotations

import logging

import caldav
from icalendar import Calendar

from .config import CALDAV_BASE_URL, CALDAV_PASSWORD, CALDAV_USERNAME

log = logging.getLogger(__name__)

_MEAL_EMOJI = "🍽"


def _get_calendar_for_event(principal: caldav.Principal, uid: str):
    for cal in principal.calendars():
        try:
            results = cal.search(uid=uid, event=True)
            if results:
                return cal, results[0]
        except Exception:
            continue
    return None, None


def patch_event(
    uid: str,
    *,
    new_location: str | None = None,
    new_url: str | None = None,
) -> None:
    """Patch SUMMARY (add emoji), LOCATION, and/or URL on the event with the given UID.

    Only updates fields where a new value is provided (location/url) or where
    the emoji is missing (summary). Skips the write entirely if nothing changed.
    """
    try:
        client = caldav.DAVClient(
            url=CALDAV_BASE_URL,
            username=CALDAV_USERNAME,
            password=CALDAV_PASSWORD,
        )
        principal = client.principal()
        cal, vevent_obj = _get_calendar_for_event(principal, uid)
        if vevent_obj is None:
            log.warning("patch_event: could not find event uid=%s", uid)
            return

        ical = Calendar.from_ical(vevent_obj.data)
        changed = False

        for component in ical.walk("VEVENT"):
            # SUMMARY — prepend emoji if missing
            summary = str(component.get("SUMMARY", ""))
            if not summary.startswith(_MEAL_EMOJI):
                component["SUMMARY"] = f"{_MEAL_EMOJI} {summary}"
                changed = True

            # LOCATION
            if new_location:
                existing = str(component.get("LOCATION", "")).strip()
                if existing != new_location:
                    if "LOCATION" in component:
                        del component["LOCATION"]
                    component.add("LOCATION", new_location)
                    changed = True

            # URL
            if new_url:
                existing_url = str(component.get("URL", "")).strip()
                if not existing_url:
                    component.add("URL", new_url)
                    changed = True

        if not changed:
            log.info("patch_event: nothing to update for uid=%s", uid)
            return

        vevent_obj.data = ical.to_ical().decode()
        vevent_obj.save()
        log.info("patch_event: updated event uid=%s", uid)

    except Exception:
        log.exception("patch_event failed for uid=%s", uid)
