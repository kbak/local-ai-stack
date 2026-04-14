"""Parse city/location from calendar events.

Fast path: explicit LOCATION field on the event.
Slow path: LLM call with optional searxng tool use.
"""

from __future__ import annotations

import json
import logging

import httpx
from openai import OpenAI

from .config import (
    INFERENCE_API_KEY,
    INFERENCE_BASE_URL,
    INFERENCE_MODEL,
    SEARXNG_URL,
)

log = logging.getLogger(__name__)

_client: OpenAI | None = None


def _llm() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=INFERENCE_BASE_URL, api_key=INFERENCE_API_KEY)
    return _client


_SYSTEM_PROMPT = """\
You are a location extractor. Given a calendar event, determine if it represents \
travel to a specific city. If it does, return a JSON object with:
  {"city": "<city name, English>", "confidence": "high"|"medium"|"low"}
If the event is NOT travel-related or you cannot determine a city, return:
  {"city": null, "confidence": null}

Rules:
- "city" must be a real city name in English (e.g. "Warsaw", "San Diego", "London").
- "high": explicit flight arrival, hotel check-in, or clear "arriving in <city>" phrasing.
- "medium": hotel name with city, "driving to X", "going to X" with a recognisable place.
- "low": vague but plausible travel signal.
- Use the search tool if you are unsure whether a string refers to a city or location.
- Return ONLY the JSON object, no extra text.
"""

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the web via SearXNG to look up a place, airport code, or venue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"],
            },
        },
    }
]


def _searxng_search(query: str) -> str:
    try:
        resp = httpx.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json", "categories": "general"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])[:3]
        return json.dumps([
            {"title": r.get("title"), "content": r.get("content")}
            for r in results
        ])
    except Exception as e:
        return json.dumps({"error": str(e)})


def _run_tool_loop(messages: list[dict]) -> dict:
    """Run LLM with tool use until it returns a final answer."""
    for _ in range(5):  # max 5 turns
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
                result = _searxng_search(tc.function.arguments
                                         if isinstance(tc.function.arguments, str)
                                         else json.dumps(tc.function.arguments))
                # parse query from arguments
                try:
                    args = json.loads(tc.function.arguments)
                    result = _searxng_search(args.get("query", ""))
                except Exception:
                    pass
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            continue

        # final answer
        content = (msg.content or "").strip()
        # strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            log.warning("LLM returned non-JSON: %s", content)
            return {"city": None, "confidence": None}

    return {"city": None, "confidence": None}


def parse_event_location(
    summary: str,
    description: str,
    start_iso: str,
    end_iso: str,
    tzid: str,
) -> tuple[str | None, str | None]:
    """
    Returns (city, confidence) or (None, None) if not travel-related.
    Called only for events WITHOUT an explicit LOCATION field.
    """
    user_content = (
        f"Event summary: {summary}\n"
        f"Description: {description or '(none)'}\n"
        f"Start: {start_iso} (TZID: {tzid or 'UTC'})\n"
        f"End: {end_iso}"
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    try:
        result = _run_tool_loop(messages)
        return result.get("city"), result.get("confidence")
    except Exception:
        log.exception("LLM parse failed for event: %s", summary)
        return None, None
