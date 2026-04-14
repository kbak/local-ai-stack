"""LLM agent used for classification only.

Tools available to the LLM:
  - search(query)          → SearXNG
  - get_location_at(dt)    → location-tracker
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
