"""Semantic Scholar academic search via local MCP proxy."""

import httpx
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/semantic-scholar/mcp"


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
def search_papers(query: str, limit: int = 5) -> str:
    """Search for academic papers on Semantic Scholar.

    Use when the user wants to find peer-reviewed papers, research with citations,
    or academic literature on a topic. Complements arXiv with citation data.

    Args:
        query: Search query (topic, title, or author).
        limit: Number of results to return.
    """
    try:
        return _call_mcp("search_papers", {"query": query, "limit": limit})
    except Exception as e:
        return f"Semantic Scholar search failed: {e}"


@tool
def get_paper(paper_id: str) -> str:
    """Get details of a specific paper from Semantic Scholar by its ID.

    Use when you have a Semantic Scholar paper ID or DOI and want full details.

    Args:
        paper_id: Semantic Scholar paper ID or DOI.
    """
    try:
        return _call_mcp("get_paper", {"paper_id": paper_id})
    except Exception as e:
        return f"Semantic Scholar paper fetch failed: {e}"
