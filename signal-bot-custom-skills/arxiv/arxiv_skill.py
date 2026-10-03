"""arXiv academic paper search via local MCP proxy."""

from stack_shared.mcp_client import call_skill_mcp as call_mcp
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/arxiv/mcp"


def _call_mcp(tool_name: str, arguments: dict, timeout: int = 20) -> str:
    return call_mcp(MCP_URL, tool_name, arguments, timeout)


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
