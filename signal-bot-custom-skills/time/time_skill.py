"""Time and timezone tools via local MCP proxy."""

import httpx
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/time/mcp"


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
def get_current_time(timezone: str = "UTC") -> str:
    """Get the current time in a specified timezone.

    Use when the user asks what time it is, or asks for the current time in a city or timezone.

    Args:
        timezone: IANA timezone name (e.g. 'America/New_York', 'Europe/Warsaw', 'UTC').
    """
    try:
        return _call_mcp("get_current_time", {"timezone": timezone})
    except Exception as e:
        return f"Time lookup failed: {e}"


@tool
def convert_time(time: str, from_timezone: str, to_timezone: str) -> str:
    """Convert a time from one timezone to another.

    Use when the user wants to convert a time between timezones.

    Args:
        time: Time string in HH:MM format (24h).
        from_timezone: Source IANA timezone (e.g. 'America/New_York').
        to_timezone: Target IANA timezone (e.g. 'Europe/Warsaw').
    """
    try:
        return _call_mcp("convert_time", {"time": time, "source_timezone": from_timezone, "target_timezone": to_timezone})
    except Exception as e:
        return f"Time conversion failed: {e}"
