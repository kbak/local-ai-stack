"""CalDAV fetch for location-tracker — thin wrapper around stack_shared."""

from __future__ import annotations

from stack_shared.caldav_fetch import RawEvent, fetch_events as _fetch

from .config import (
    CALDAV_BASE_URL,
    CALDAV_PASSWORD,
    CALDAV_USERNAME,
    CALENDAR_NAMES,
    LOCAL_TIMEZONE,
    LOOKBACK_DAYS,
    LOOKAHEAD_DAYS,
)

__all__ = ["RawEvent", "fetch_events"]


def fetch_events() -> list[RawEvent]:
    return _fetch(
        base_url=CALDAV_BASE_URL,
        username=CALDAV_USERNAME,
        password=CALDAV_PASSWORD,
        calendar_names=CALENDAR_NAMES,
        lookback_days=LOOKBACK_DAYS,
        lookahead_days=LOOKAHEAD_DAYS,
        local_tz=LOCAL_TIMEZONE,
    )
