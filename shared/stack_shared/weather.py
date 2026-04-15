"""Fetch weather forecast via the MCP weather server."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from stack_shared.mcp_client import call_mcp

log = logging.getLogger(__name__)


def get_weather(
    city: str,
    event_dt: datetime,
    *,
    mcp_proxy_url: str,
    mcp_auth_token: str,
) -> str | None:
    """Return a one-line weather summary for city at event_dt, or None on failure."""
    try:
        date_str = event_dt.strftime("%Y-%m-%d")
        raw = call_mcp(
            f"{mcp_proxy_url}/servers/weather/mcp",
            "get_weather_byDateTimeRange",
            {"city": city, "start_date": date_str, "end_date": date_str},
            auth_token=mcp_auth_token,
        )
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(0))
        entries = data.get("weather_data", [])
        if not entries:
            return None

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
