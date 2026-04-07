"""Wikipedia search and article retrieval via local MCP proxy."""

import httpx
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/wikipedia/mcp"


def _call_mcp(tool_name: str, arguments: dict, timeout: int = 20) -> str:
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
def search_wikipedia(query: str) -> str:
    """Search Wikipedia for articles matching a query.

    Use when the user wants to find Wikipedia articles about a topic, person, place, or concept.

    Args:
        query: Search query string.
    """
    try:
        return _call_mcp("search_wikipedia", {"query": query})
    except Exception as e:
        return f"Wikipedia search failed: {e}"


@tool
def get_article(title: str) -> str:
    """Get a Wikipedia article summary by title.

    Use when the user wants to read about a specific Wikipedia topic and you know the article title.

    Args:
        title: Wikipedia article title.
    """
    try:
        return _call_mcp("get_summary", {"title": title})
    except Exception as e:
        return f"Wikipedia article fetch failed: {e}"
