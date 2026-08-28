"""Compact, structured web-search MCP server backed by SearXNG."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("searxng")
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080").rstrip("/")
ALLOWED_TIME_RANGES = {"day", "month", "year"}
CACHE_TTL_SECONDS = 300
_cache: dict[tuple[tuple[str, str], ...], tuple[float, dict[str, Any]]] = {}


def _clean_query(query: str) -> str:
    query = query.strip()
    if query.startswith("{") and query.endswith("}"):
        try:
            value = json.loads(query)
            if isinstance(value, dict) and isinstance(value.get("query"), str):
                return value["query"].strip()
        except json.JSONDecodeError:
            pass
    return query


def _simplify_query(query: str) -> str:
    """Make one conservative retry query without structured punctuation."""
    simplified = re.sub(r"[{}\[\]\"']", " ", query)
    simplified = re.sub(r"\s+", " ", simplified).strip()
    return simplified


def _request(params: dict[str, str | int]) -> dict[str, Any]:
    cache_key = tuple(sorted((key, str(value)) for key, value in params.items()))
    cached = _cache.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    url = f"{SEARXNG_URL}/search?{urlencode(params)}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "local-ai-stack-search/1.0"})
    with urlopen(request, timeout=20) as response:
        data = json.load(response)
    if data.get("results"):
        _cache[cache_key] = (now, data)
    return data


@mcp.tool()
def web_search(
    query: str,
    max_results: int = 8,
    page: int = 1,
    time_range: str | None = None,
    language: str = "all",
    categories: str | None = None,
    engines: str | None = None,
    site: str | None = None,
) -> dict[str, Any]:
    """Search the web and return compact structured results.

    Start with 5-8 results. Fetch the most promising 2-3 URLs with the separate
    fetch tool before answering research questions. Use `site` for a domain
    restriction, `categories` for comma-separated SearXNG categories, and
    `engines` only when a specific comma-separated engine list is needed.
    """
    clean_query = _clean_query(query)
    if not clean_query:
        return {"error": "query must not be empty", "results": []}

    max_results = max(1, min(max_results, 20))
    page = max(1, page)
    if site:
        clean_query = f"site:{site.strip()} {clean_query}"

    params: dict[str, str | int] = {
        "q": clean_query,
        "format": "json",
        "pageno": page,
        "language": language,
    }
    if time_range in ALLOWED_TIME_RANGES:
        params["time_range"] = time_range
    if categories:
        params["categories"] = categories
    if engines:
        params["engines"] = engines

    try:
        data = _request(params)
    except Exception as exc:
        return {"query": clean_query, "error": str(exc), "results": []}

    raw_results = data.get("results") or []
    retried = False
    if not raw_results:
        retry_query = _simplify_query(clean_query)
        if retry_query and retry_query != clean_query:
            retry_params = dict(params)
            retry_params["q"] = retry_query
            try:
                retry_data = _request(retry_params)
                retried = True
                if retry_data.get("results"):
                    data = retry_data
                    raw_results = data["results"]
            except Exception:
                pass
    results = []
    for item in raw_results[:max_results]:
        result = {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
            "score": item.get("score", 0),
            "engines": item.get("engines", []),
        }
        published = item.get("publishedDate") or item.get("published_date")
        if published:
            result["published_date"] = published
        results.append(result)

    return {
        "query": clean_query,
        "page": page,
        "result_count": len(results),
        "retried": retried,
        "results": results,
        "engine_errors": data.get("unresponsive_engines", []),
        "suggestions": data.get("suggestions", [])[:5],
    }


if __name__ == "__main__":
    mcp.run()
