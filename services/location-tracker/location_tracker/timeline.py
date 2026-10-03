"""Derive location spans from raw anchors, and query them."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .config import HOME_CITY
from .state import LocationSpan, RawAnchor

log = logging.getLogger(__name__)

_FAR_FUTURE = "9999-12-31T23:59:59+00:00"


def _utc(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_spans(anchors: dict[str, RawAnchor]) -> list[LocationSpan]:
    """
    Derive a sorted list of LocationSpans from raw anchors.

    Each travel anchor marks: "from event.end onwards, user is in this city."
    (The user arrives at the destination when the event ends — e.g. when the
    flight lands or the drive ends.)

    Between the end of one span and the start of the next anchor, the city
    from the most recent anchor persists. Before all anchors: HOME_CITY.
    """
    travel = sorted(
        [a for a in anchors.values() if a.city],
        key=lambda a: _utc(a.end_utc),
    )

    if not travel:
        return []

    spans: list[LocationSpan] = []

    for i, anchor in enumerate(travel):
        from_utc = anchor.end_utc  # city starts when travel event ends (arrival)
        # Span ends when the next anchor's travel begins (departure)
        if i + 1 < len(travel):
            to_utc = travel[i + 1].start_utc
        else:
            to_utc = None  # open-ended — still there

        spans.append(LocationSpan(
            from_utc=from_utc,
            to_utc=to_utc,
            city=anchor.city,
            confidence=anchor.confidence,
            source=anchor.source,
        ))

    log.info("Built %d location spans from %d anchors", len(spans), len(travel))
    return spans


def get_location_at(query_dt: datetime, spans: list[LocationSpan]) -> dict:
    """
    Returns {city, confidence, source} for the given datetime.

    Searches the pre-computed spans list. Falls back to HOME_CITY / unknown.
    """
    if query_dt.tzinfo is None:
        query_dt = query_dt.replace(tzinfo=timezone.utc)
    query_dt = query_dt.astimezone(timezone.utc)

    for span in spans:
        from_dt = _utc(span.from_utc)
        to_dt = _utc(span.to_utc) if span.to_utc else _utc(_FAR_FUTURE)
        if from_dt <= query_dt < to_dt:
            return {
                "city": span.city,
                "confidence": span.confidence,
                "source": span.source,
            }

    if HOME_CITY:
        return {
            "city": HOME_CITY,
            "confidence": "fallback",
            "source": "HOME_CITY",
        }
    return {
        "city": "unknown",
        "confidence": "fallback",
        "source": "No location data available",
    }
