"""Weather data via local MCP proxy."""

from stack_shared.mcp_client import call_skill_mcp as call_mcp
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/weather/mcp"


def _call_mcp(tool_name: str, arguments: dict, timeout: int = 15) -> str:
    return call_mcp(MCP_URL, tool_name, arguments, timeout)


@tool
def get_current_weather(location: str) -> str:
    """Get the current weather for a location.

    Use when the user asks about current weather, temperature, or conditions in a city or place.

    Args:
        location: City name or location (e.g. 'Warsaw', 'New York, US').
    """
    try:
        return _call_mcp("get_current_weather", {"city": location})
    except Exception as e:
        return f"Weather lookup failed: {e}"


@tool
def get_forecast(location: str, days: int = 3) -> str:
    """Get a weather forecast for a location.

    Use when the user asks about upcoming weather or a multi-day forecast.

    Args:
        location: City name or location.
        days: Number of days to forecast (1-7).
    """
    import datetime
    today = datetime.date.today()
    end = today + datetime.timedelta(days=days)
    try:
        return _call_mcp("get_weather_byDateTimeRange", {"city": location, "start_date": today.isoformat(), "end_date": end.isoformat()})
    except Exception as e:
        return f"Weather forecast failed: {e}"
