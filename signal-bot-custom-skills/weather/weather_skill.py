"""Weather data via local MCP proxy."""

import httpx
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/weather/mcp"


def _call_mcp(tool_name: str, arguments: dict, timeout: int = 15) -> str:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        init = client.post(MCP_URL, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "signal-bot", "version": "1.0"}}})
        init.raise_for_status()
        session_id = init.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("No session ID returned")
        resp = client.post(MCP_URL, headers={**headers, "mcp-session-id": session_id}, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}})
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        content = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


@tool
def get_current_weather(location: str) -> str:
    """Get the current weather for a location.

    Use when the user asks about current weather, temperature, or conditions in a city or place.

    Args:
        location: City name or location (e.g. 'Warsaw', 'New York, US').
    """
    try:
        return _call_mcp("get_current_weather", {"location": location})
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
    try:
        return _call_mcp("get_weather_byDateTimeRange", {"location": location, "days": days})
    except Exception as e:
        return f"Weather forecast failed: {e}"
