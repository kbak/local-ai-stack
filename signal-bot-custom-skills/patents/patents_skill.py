"""US patent search via local MCP proxy."""

import httpx
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/patents/mcp"


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
def search_patents(query: str, limit: int = 5) -> str:
    """Search US patents and patent applications via USPTO.

    Use when the user wants to search for patents, find prior art, or look up patent information.

    Args:
        query: Search query (keywords, inventor name, assignee, or patent number).
        limit: Maximum number of results to return.
    """
    try:
        return _call_mcp("ppubs_search_patents", {"query": query, "limit": limit})
    except Exception as e:
        return f"Patent search failed: {e}"
