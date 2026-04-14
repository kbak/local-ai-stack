"""LLM agent with tools for classification and enrichment.

All tools available to the LLM:
  - search(query)          → SearXNG
  - fetch(url)             → mcp-proxy fetch tool
  - get_weather(city, dt)  → mcp-proxy weather tool
  - get_location_at(dt)    → location-tracker

The same tool loop is used for both classification and enrichment —
enrichment just gets a richer prompt and more tool budget.
"""

from __future__ import annotations

import json
import logging

import httpx
from openai import OpenAI
from stack_shared.mcp_client import call_mcp

from .config import (
    INFERENCE_API_KEY,
    INFERENCE_BASE_URL,
    INFERENCE_MODEL,
    LOCATION_TRACKER_URL,
    MCP_AUTH_TOKEN,
    MCP_PROXY_URL,
    SEARXNG_URL,
)

log = logging.getLogger(__name__)

_client: OpenAI | None = None


def _llm() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=INFERENCE_BASE_URL, api_key=INFERENCE_API_KEY)
    return _client


# ── Tool definitions ──────────────────────────────────────────────────────────

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the web via SearXNG. Use for restaurant lookups, menus, ratings, city resolution.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch",
            "description": "Fetch the full text content of a URL. Use for restaurant websites, menu pages, review pages.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather forecast for a city at a specific date/time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "datetime_iso": {"type": "string", "description": "ISO 8601 datetime"},
                },
                "required": ["city", "datetime_iso"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_location_at",
            "description": "Get the user's city at a given datetime from the location tracker.",
            "parameters": {
                "type": "object",
                "properties": {
                    "datetime_iso": {"type": "string", "description": "ISO 8601 datetime"},
                },
                "required": ["datetime_iso"],
            },
        },
    },
]


# ── Tool execution ────────────────────────────────────────────────────────────

def _execute_tool(name: str, args: dict) -> str:
    try:
        if name == "search":
            return _searxng(args["query"])
        elif name == "fetch":
            return _mcp_proxy("fetch", "fetch", {"url": args["url"]})
        elif name == "get_weather":
            return _mcp_proxy("weather", "get_weather_byDateTimeRange", {
                "city": args["city"],
                "start_date": args["datetime_iso"][:10],
                "end_date": args["datetime_iso"][:10],
            })
        elif name == "get_location_at":
            return call_mcp(
                LOCATION_TRACKER_URL,
                "get_location_at",
                {"datetime_iso": args["datetime_iso"]},
                auth_token=MCP_AUTH_TOKEN,
            )
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        log.warning("Tool %s failed: %s", name, e)
        return json.dumps({"error": str(e)})


def _searxng(query: str) -> str:
    try:
        resp = httpx.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json", "categories": "general"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])[:5]
        return json.dumps([
            {"title": r.get("title"), "content": r.get("content"), "url": r.get("url")}
            for r in results
        ])
    except Exception as e:
        return json.dumps({"error": str(e)})


def _mcp_proxy(server: str, tool: str, args: dict) -> str:
    return call_mcp(
        f"{MCP_PROXY_URL}/servers/{server}/mcp",
        tool,
        args,
        auth_token=MCP_AUTH_TOKEN,
    )


# ── Agent loop ────────────────────────────────────────────────────────────────

def run_agent(system_prompt: str, user_prompt: str, max_turns: int = 20) -> str:
    """Run the LLM with tools until it produces a final text response."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for _ in range(max_turns):
        response = _llm().chat.completions.create(
            model=INFERENCE_MODEL,
            messages=messages,
            tools=_TOOLS,
            tool_choice="auto",
            temperature=0,
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            messages.append(msg)
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                result = _execute_tool(tc.function.name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            continue

        return (msg.content or "").strip()

    raise RuntimeError("Agent reached max turns without producing a final response")
