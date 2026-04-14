"""Classify calendar events as meal events.

Returns {is_meal, venue, city} or None if not a meal event.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from stack_shared.caldav_fetch import RawEvent

from .agent import run_agent

log = logging.getLogger(__name__)

_CLASSIFY_SYSTEM = """\
You are a calendar event classifier. Your job is to determine whether a calendar
event represents a confirmed booking or plan to eat/drink at a specific named venue
(restaurant, café, bar, wine bar, etc.).

You have access to tools: search (web search) and get_location_at (user's location).

Rules:
- Only return is_meal=true if you are CONFIDENT this is a named dining venue booking.
- A specific restaurant name as the event title = strong YES signal.
- Vague titles like "dinner", "lunch with Sarah", "hotel drinks" = NO (not a specific venue).
- Personal notes that happen to mention food ("let's grab wine", "skip breakfast") = NO.
- Hotels, gyms, offices, airports = NO unless the event title is clearly a restaurant inside.
- If the event description contains signals that override the title (e.g. "going to the hotel",
  "personal errand", "meeting"), lean toward NO.
- If the explicit location field is set, use it to confirm the venue type with one search.
- If unsure after searching, return is_meal=false. False positives are worse than false negatives.
- Many restaurant names embed the city: "Nobu Las Vegas", "Zinque Scottsdale" — extract it.
- If no city found in the title, call get_location_at with the event start datetime.

Respond with a JSON object only:
{
  "is_meal": true | false,
  "venue": "<restaurant name or null>",
  "city": "<city name or null>"
}
No extra text.
"""


@dataclass
class ClassifyResult:
    is_meal: bool
    venue: str | None
    city: str | None


def classify(event: RawEvent) -> ClassifyResult:
    user_prompt = (
        f"Summary: {event.summary}\n"
        f"Location field: {event.location or '(empty)'}\n"
        f"Description: {event.description or '(none)'}\n"
        f"Start: {event.start.isoformat()}\n"
        f"End: {event.end.isoformat()}"
    )

    raw = run_agent(_CLASSIFY_SYSTEM, user_prompt, max_turns=8)

    # Strip markdown fences if present
    content = raw.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    try:
        data = json.loads(content)
        return ClassifyResult(
            is_meal=bool(data.get("is_meal", False)),
            venue=data.get("venue") or None,
            city=data.get("city") or None,
        )
    except (json.JSONDecodeError, KeyError):
        log.warning("Classifier returned non-JSON for '%s': %s", event.summary, raw)
        return ClassifyResult(is_meal=False, venue=None, city=None)
