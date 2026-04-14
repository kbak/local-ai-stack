"""Enrich a meal event with rating, full menu, and weather.

Returns a formatted briefing string ready to send via Signal.
"""

from __future__ import annotations

import logging

from stack_shared.caldav_fetch import RawEvent

from .agent import run_agent
from .classifier import ClassifyResult

log = logging.getLogger(__name__)

_ENRICH_SYSTEM = """\
You are a personal assistant writing a pre-meal briefing for your user.
You have access to tools: search, fetch, get_weather.
Use at most 6 tool calls total. Budget: 1 for weather, 1 for reviews, 1-2 for menu, done.

Follow these steps in order:

STEP 1 — Weather (do this first):
Call get_weather with the city and the event datetime. Store the result.

STEP 2 — About (1 search, no more):
Search "{restaurant} {city} reviews". Read the snippets. \
Extract: cuisine type, price range, and the best rating you can find (Google Maps, \
Yelp, OpenTable, or any other source — whatever is in the snippets). \
Stop after this one search regardless of what you find.

STEP 3 — Menu link:
Search "{restaurant} {city} menu" to find their menu page URL. \
Return the direct URL to the menu (e.g. https://restaurant.com/menu). \
Do NOT link to the homepage — find the actual /menu or /menus subpage. \
If the restaurant's own site has no menu page, use an OpenTable or Yelp menu link.

STEP 4 — Google Maps link:
Construct: https://www.google.com/maps/search/?api=1&query={restaurant}+{city} \
(URL-encode spaces as +).

Then write the briefing using EXACTLY this format, no extra sections:

🍽 {restaurant}, {city}
{date and time, local timezone, human-readable}

**About:** {cuisine type, price range} · {rating}★ on {source} ({review count} reviews)
**Menu:** {direct URL to menu page}
**Maps:** {Google Maps URL}
**Weather:** {temperature and conditions} · {one practical note, max 10 words}
"""


def enrich(event: RawEvent, classification: ClassifyResult) -> str:
    venue = classification.venue or event.summary
    city = classification.city or "unknown city"

    user_prompt = (
        f"Restaurant: {venue}\n"
        f"City: {city}\n"
        f"Event date/time: {event.start.isoformat()}\n"
        f"Explicit location field: {event.location or '(none)'}"
    )

    log.info("Enriching '%s' in %s at %s", venue, city, event.start.isoformat())
    briefing = run_agent(_ENRICH_SYSTEM, user_prompt, max_turns=15)
    log.info("Enrichment complete for '%s'", venue)
    return briefing
