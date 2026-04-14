"""Enrich a meal event with rating, menu URL, weather, and maps link.

Fully deterministic — no LLM involved.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus

import httpx

from stack_shared.caldav_fetch import RawEvent
from stack_shared.mcp_client import call_mcp

from .classifier import ClassifyResult
from .config import (
    GOOGLE_PLACES_API_KEY,
    MCP_AUTH_TOKEN,
    MCP_PROXY_URL,
    SEARXNG_URL,
)

log = logging.getLogger(__name__)


# ── Search ────────────────────────────────────────────────────────────────────

def _search(query: str) -> list[dict]:
    try:
        resp = httpx.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json", "categories": "general"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])[:5]
    except Exception as e:
        log.warning("SearXNG search failed: %s", e)
        return []


# ── Menu URL ──────────────────────────────────────────────────────────────────

_JUNK_DOMAINS = {
    "indeed.com", "linkedin.com", "glassdoor.com", "ziprecruiter.com",
    "simplyhired.com", "monster.com", "careerbuilder.com",
    "facebook.com", "instagram.com", "twitter.com", "tiktok.com",
    "youtube.com", "reddit.com", "yelp.com/search", "yellowpages.com",
    "mapquest.com", "citysearch.com", "zomato.com", "foursquare.com",
    "grubhub.com", "doordash.com", "ubereats.com", "postmates.com",
    "seamless.com", "caviar.com", "chownow.com",
    "oldtownscottsdale.com", "haute-lifestyle.com", "wanderlog.com",
    "thechambersguide.com", "postcard.inc", "menupix.com",
}

_GOOD_AGGREGATORS = ("opentable.com", "yelp.com/biz", "tripadvisor.com", "restaurantguru.com/", )


def _find_menu_url(restaurant: str, city: str) -> str | None:
    results = _search(f"{restaurant} {city} menu")
    urls = [r.get("url", "") for r in results if r.get("url")]

    def is_junk(url: str) -> bool:
        return any(j in url for j in _JUNK_DOMAINS)

    # 1. Restaurant's own site with /menu or /menus in path
    for url in urls:
        if is_junk(url):
            continue
        if not any(agg in url for agg in _GOOD_AGGREGATORS):
            if re.search(r"/menus?", url, re.I):
                return url

    # 2. Restaurant's own site (any page) — but skip if it looks like a location/info page
    for url in urls:
        if is_junk(url):
            continue
        if not any(agg in url for agg in _GOOD_AGGREGATORS):
            # Skip bare location pages like /scottsdale or /locations/...
            path = url.split("/", 3)[-1] if url.count("/") >= 3 else ""
            if re.match(r"^[a-z-]+$", path) and not re.search(r"menu", path, re.I):
                continue
            return url

    # 3. Restaurant's own site, any page including location pages
    for url in urls:
        if is_junk(url):
            continue
        if not any(agg in url for agg in _GOOD_AGGREGATORS):
            return url

    # 3. Good aggregator with /menu
    for url in urls:
        if any(agg in url for agg in _GOOD_AGGREGATORS) and re.search(r"/menu", url, re.I):
            return url

    # 4. Any good aggregator
    for url in urls:
        if any(agg in url for agg in _GOOD_AGGREGATORS):
            return url

    return None


# ── Weather ───────────────────────────────────────────────────────────────────

def _get_weather(city: str, event_dt: datetime) -> str | None:
    try:
        date_str = event_dt.strftime("%Y-%m-%d")
        raw = call_mcp(
            f"{MCP_PROXY_URL}/servers/weather/mcp",
            "get_weather_byDateTimeRange",
            {"city": city, "start_date": date_str, "end_date": date_str},
            auth_token=MCP_AUTH_TOKEN,
        )
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(0))
        entries = data.get("weather_data", [])
        if not entries:
            return None

        # Find the entry closest to the event time
        event_hour = event_dt.astimezone(timezone.utc).strftime("%H")
        best = min(entries, key=lambda e: abs(
            int(e["time"][11:13]) - int(event_hour)
        ))

        temp = round(best["temperature_c"])
        feels = round(best["apparent_temperature_c"])
        desc = best["weather_description"]
        rain_pct = best.get("precipitation_probability_percent", 0)

        line = f"{temp}°C (feels {feels}°C), {desc}"
        if rain_pct >= 30:
            line += f" · {rain_pct}% chance of rain"
        return line
    except Exception as e:
        log.warning("Weather fetch failed: %s", e)
        return None


# ── Google Places API (New) ───────────────────────────────────────────────────

def _places_lookup(venue: str, city: str) -> tuple[float | None, str | None]:
    """Return (rating, formatted_address) from Places API (New) Text Search, or (None, None)."""
    if not GOOGLE_PLACES_API_KEY:
        return None, None
    try:
        resp = httpx.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
                "X-Goog-FieldMask": "places.rating,places.formattedAddress",
            },
            json={"textQuery": f"{venue} {city}"},
            timeout=10,
        )
        resp.raise_for_status()
        places = resp.json().get("places", [])
        if not places:
            return None, None
        place = places[0]
        return place.get("rating"), place.get("formattedAddress")
    except Exception as e:
        log.warning("Places API lookup failed: %s", e)
        return None, None


# ── Maps URL ──────────────────────────────────────────────────────────────────

def _maps_url(restaurant: str, city: str) -> str:
    q = quote_plus(f"{restaurant} {city}")
    return f"https://www.google.com/maps/search/?api=1&query={q}"


# ── Location vagueness check ──────────────────────────────────────────────────

def _is_vague_location(location: str) -> bool:
    """Return True if location is empty or lacks a street number (just a city/region)."""
    loc = location.strip()
    if not loc:
        return True
    # Street addresses always contain at least one digit
    return not re.search(r"\d", loc)


# ── Main ──────────────────────────────────────────────────────────────────────

def enrich(event: RawEvent, classification: ClassifyResult) -> tuple[str, str | None]:
    """Return (briefing_text, formatted_address_or_None).

    formatted_address is non-None only when Places API returned one and the
    event location was vague — callers use it to patch the calendar event.
    """
    venue = classification.venue or event.summary
    city = classification.city or "unknown city"

    log.info("Enriching '%s' in %s", venue, city)

    # Places API — rating + address
    rating, formatted_address = _places_lookup(venue, city)

    # Only surface the address if the existing location is vague
    patch_address = formatted_address if _is_vague_location(event.location) else None

    # Other lookups
    menu_url = _find_menu_url(venue, city)
    weather = _get_weather(city, event.start)
    maps = _maps_url(venue, city)

    # Format event time in the event's local timezone
    try:
        import pytz
        tz = pytz.timezone(event.tzid) if event.tzid else timezone.utc
        local_dt = event.start.astimezone(tz)
        time_str = local_dt.strftime("%A, %b %-d at %-I:%M %p %Z")
    except Exception:
        time_str = event.start.isoformat()

    # Build briefing
    lines = [f"🍽 {venue}, {city}", time_str]

    if rating is not None:
        lines.append(f"Rating: ★ {rating}")

    if menu_url:
        lines.append(f"Menu: {menu_url}")

    lines.append(f"Maps: {maps}")

    if weather:
        lines.append(f"Weather: {weather}")

    log.info("Enrichment complete for '%s'", venue)
    return "\n".join(lines), patch_address
