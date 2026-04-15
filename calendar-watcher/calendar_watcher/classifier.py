"""Classify calendar events as meal, travel, or ignored.

Returns a ClassifyResult with event_type in {"meal", "travel", "ignored"}.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from stack_shared.caldav_fetch import RawEvent
from stack_shared.llm_agent import run_agent

from .config import (
    INFERENCE_API_KEY,
    INFERENCE_BASE_URL,
    INFERENCE_MODEL,
    LOCATION_TRACKER_URL,
    MCP_AUTH_TOKEN,
    SEARXNG_URL,
)

log = logging.getLogger(__name__)

_CLASSIFY_SYSTEM = """\
You are a calendar event classifier. Classify the event into exactly one of:
  - "meal"   — a confirmed booking or plan to eat/drink at a specific named venue
               (restaurant, café, bar, wine bar, etc.)
  - "travel" — a flight, train, or arrival event that moves the user to a new city
  - "ignored" — anything else

You have access to tools: search (web search) and get_location_at (user's location).

Rules for "meal":
- Only classify as meal if you are CONFIDENT this is a named dining venue booking.
- A specific restaurant name as the event title = strong YES.
- Vague titles like "dinner", "lunch with Sarah", "hotel drinks" = NO.
- Personal notes that happen to mention food = NO.
- Hotels, gyms, offices, airports = NO unless the event title is clearly a restaurant inside.
- If unsure after searching, return "ignored". False positives are worse than false negatives.
- Many restaurant names embed the city: "Nobu Las Vegas", "Zinque Scottsdale" — extract it.
- If no city found in the title, call get_location_at with the event start datetime.

Rules for "travel":
- Flights (titles like "NYC → LAX", "Flight to Paris", "AA 123 JFK-LHR") = travel.
- Train journeys between cities = travel.
- "Arrival in X", "Check-in", "Land in X" type events = travel.
- Extract the DESTINATION city (not origin) as the city field.
- For flights, the destination is the last city in the route.

Respond with a JSON object only:
{
  "event_type": "meal" | "travel" | "ignored",
  "venue": "<restaurant name or null>",
  "city": "<destination city or null>"
}
No extra text.
"""


@dataclass
class ClassifyResult:
    event_type: str       # "meal" | "travel" | "ignored"
    venue: str | None     # for meal events
    city: str | None      # destination city (travel) or venue city (meal)

    @property
    def is_meal(self) -> bool:
        return self.event_type == "meal"

    @property
    def is_travel(self) -> bool:
        return self.event_type == "travel"


def classify(event: RawEvent) -> ClassifyResult:
    user_prompt = (
        f"Summary: {event.summary}\n"
        f"Location field: {event.location or '(empty)'}\n"
        f"Description: {event.description or '(none)'}\n"
        f"Start: {event.start.isoformat()}\n"
        f"End: {event.end.isoformat()}"
    )

    raw = run_agent(
        _CLASSIFY_SYSTEM,
        user_prompt,
        inference_base_url=INFERENCE_BASE_URL,
        inference_api_key=INFERENCE_API_KEY,
        inference_model=INFERENCE_MODEL,
        searxng_url=SEARXNG_URL,
        location_tracker_url=LOCATION_TRACKER_URL,
        location_tracker_auth_token=MCP_AUTH_TOKEN,
        max_turns=8,
    )

    content = raw.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    try:
        data = json.loads(content)
        return ClassifyResult(
            event_type=data.get("event_type", "ignored"),
            venue=data.get("venue") or None,
            city=data.get("city") or None,
        )
    except (json.JSONDecodeError, KeyError):
        log.warning("Classifier returned non-JSON for '%s': %s", event.summary, raw)
        return ClassifyResult(event_type="ignored", venue=None, city=None)
