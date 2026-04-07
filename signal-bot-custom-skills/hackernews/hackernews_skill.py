"""Hacker News stories and search via local MCP proxy."""

import httpx
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/hackernews/mcp"


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
def get_top_stories(story_type: str = "top", limit: int = 10) -> str:
    """Get top stories from Hacker News.

    Use when the user asks about Hacker News, tech news, or what's trending on HN.

    Args:
        story_type: Type of stories - 'top', 'new', 'best', 'ask', 'show', or 'job'.
        limit: Number of stories to return.
    """
    try:
        return _call_mcp("get_stories", {"story_type": story_type, "limit": limit})
    except Exception as e:
        return f"Hacker News fetch failed: {e}"


@tool
def search_stories(query: str, limit: int = 10) -> str:
    """Search Hacker News stories by keyword.

    Use when the user wants to find specific Hacker News discussions or posts about a topic.

    Args:
        query: Search query string.
        limit: Maximum number of results.
    """
    try:
        return _call_mcp("search_stories", {"query": query, "limit": limit})
    except Exception as e:
        return f"Hacker News search failed: {e}"
