"""Time and timezone tools via local MCP proxy."""

from stack_shared.mcp_client import call_skill_mcp as call_mcp
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/time/mcp"


def _call_mcp(tool_name: str, arguments: dict, timeout: int = 15) -> str:
    return call_mcp(MCP_URL, tool_name, arguments, timeout)


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
