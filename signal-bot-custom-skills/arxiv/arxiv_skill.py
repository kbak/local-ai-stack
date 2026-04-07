"""arXiv academic paper search via local MCP proxy."""

import httpx
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/arxiv/mcp"


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
def search_papers(query: str, max_results: int = 5) -> str:
    """Search for academic papers on arXiv.

    Use when the user wants to find research papers, preprints, or academic publications on a topic.

    Args:
        query: Search query (topic, title keywords, author name).
        max_results: Maximum number of papers to return.
    """
    try:
        return _call_mcp("search_papers", {"query": query, "max_results": max_results})
    except Exception as e:
        return f"arXiv search failed: {e}"


@tool
def get_abstract(paper_id: str) -> str:
    """Get the abstract and details of a specific arXiv paper by its ID.

    Use when the user wants details about a specific arXiv paper.

    Args:
        paper_id: arXiv paper ID (e.g. '2301.07041' or 'arxiv:2301.07041').
    """
    try:
        return _call_mcp("get_abstract", {"paper_id": paper_id})
    except Exception as e:
        return f"arXiv paper fetch failed: {e}"
