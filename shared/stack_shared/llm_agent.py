"""Generic LLM tool-calling agent.

Tools available to the LLM:
  - search(query)          → SearXNG
  - get_location_at(dt)    → location-tracker
"""

from __future__ import annotations

import json
import logging

import httpx
from stack_shared.llm_client import get_client
from stack_shared.llm_model import resolve_model
from stack_shared.mcp_client import call_mcp

log = logging.getLogger(__name__)


# ── Tool definitions ──────────────────────────────────────────────────────────

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the web via SearXNG. Use for restaurant lookups, menus, ratings, city resolution, flight destinations.",
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

def _execute_tool(
    name: str,
    args: dict,
    searxng_url: str,
    location_tracker_url: str,
    location_tracker_auth_token: str,
) -> str:
    try:
        if name == "search":
            return _searxng(args["query"], searxng_url)
        elif name == "get_location_at":
            return call_mcp(
                location_tracker_url,
                "get_location_at",
                {"datetime_iso": args["datetime_iso"]},
                auth_token=location_tracker_auth_token,
            )
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        log.warning("Tool %s failed: %s", name, e)
        return json.dumps({"error": str(e)})


def _searxng(query: str, searxng_url: str) -> str:
    try:
        resp = httpx.get(
            f"{searxng_url}/search",
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

def run_agent(
    system_prompt: str,
    user_prompt: str,
    *,
    inference_base_url: str | None = None,
    inference_api_key: str | None = None,
    inference_model: str | None = None,
    searxng_url: str,
    location_tracker_url: str,
    location_tracker_auth_token: str,
    max_turns: int = 20,
) -> str:
    """Run the LLM with tools until it produces a final text response.

    `inference_*` kwargs are optional - they resolve from env / llama-swap
    via the shared `llm_client` + `llm_model` helpers when omitted.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    llm = get_client(base_url=inference_base_url, api_key=inference_api_key)
    model_id = inference_model or resolve_model(base_url=inference_base_url)

    for _ in range(max_turns):
        response = llm.chat.completions.create(
            model=model_id,
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
                result = _execute_tool(
                    tc.function.name,
                    args,
                    searxng_url=searxng_url,
                    location_tracker_url=location_tracker_url,
                    location_tracker_auth_token=location_tracker_auth_token,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            continue

        return (msg.content or "").strip()

    raise RuntimeError("Agent reached max turns without producing a final response")
