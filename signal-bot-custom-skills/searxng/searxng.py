"""Web search via local SearXNG metasearch engine."""

import httpx
from strands import tool

SEARXNG_URL = "http://searxng:8081"


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using the local SearXNG metasearch engine.

    Use this tool when the user asks to look something up, research a topic,
    find current information, news, or when you need facts you don't know.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return.
    """
    try:
        resp = httpx.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json", "pageno": 1},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])[:max_results]

        if not results:
            return "No results found."

        formatted = []
        for r in results:
            title = r.get("title", "")
            content = r.get("content", "")
            url = r.get("url", "")
            formatted.append(f"**{title}**\n{content}\nURL: {url}")
        return "\n\n---\n\n".join(formatted)
    except Exception as e:
        return f"Search failed: {e}"
