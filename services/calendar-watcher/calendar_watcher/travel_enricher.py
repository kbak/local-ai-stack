"""Enrich a travel anchor event with weather forecast."""

from __future__ import annotations

import logging
from datetime import timezone

from stack_shared.caldav_fetch import RawEvent
from stack_shared.weather import get_weather

from .classifier import ClassifyResult
from .config import MCP_PROXY_URL

log = logging.getLogger(__name__)


def enrich(event: RawEvent, classification: ClassifyResult) -> str:
    """Return a weather briefing for the travel destination."""
    city = classification.city or "unknown city"

    log.info("Enriching travel to '%s'", city)

    try:
        import pytz
        tz = pytz.timezone(event.tzid) if event.tzid else timezone.utc
        local_dt = event.start.astimezone(tz)
        time_str = local_dt.strftime("%A, %b %-d at %-I:%M %p %Z")
    except Exception:
        time_str = event.start.isoformat()

    weather = get_weather(city, event.start, mcp_proxy_url=MCP_PROXY_URL, mcp_auth_token="")

    lines = [f"✈️ Arriving {city}", time_str]
    if weather:
        lines.append(f"Weather: {weather}")
    else:
        lines.append("Weather: unavailable")

    log.info("Travel enrichment complete for '%s'", city)
    return "\n".join(lines)
