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
    HOME_CITY,
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


_SYSTEM_PROMPT = f"""\
You are a travel detector. Given a calendar event, determine if it represents \
travel AWAY FROM HOME requiring an overnight stay or multi-day presence in a different city.
Home city is: {HOME_CITY or "unknown"}.

If the event represents such travel, return:
  {{"city": "<destination city name, English>", "confidence": "high"|"medium"|"low"}}
Otherwise return:
  {{"city": null, "confidence": null}}

Rules:
- ONLY return a city for CONFIRMED travel: actual flights, confirmed hotel check-ins,
  "arriving in X", "flying to X", "hotel [name] [city]".
- Planning notes, ideas, wishful thinking ("plan summer in X", "thinking of going to X",
  "maybe X trip", "research X") = null. Not confirmed travel.
- Local events — concerts, restaurants, meetings, errands, day trips — are NOT travel,
  even if they have an explicit venue address in another city.
- A venue address or city in the LOCATION field does NOT make something travel.
  Use the event type (flight? hotel? confirmed booking?) to decide.
- When in doubt, return null. False positives corrupt the timeline permanently.
- "high": explicit flight with destination city, or confirmed hotel check-in with city.
- "medium": "driving to X overnight", confirmed multi-night stay with city.
- Do NOT use "low" — if confidence would be low, return null instead.
- Use the search tool only if you need to identify an airport code or city name.
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
    location_hint: str = "",
) -> tuple[str | None, str | None]:
    """
    Returns (city, confidence) or (None, None) if not travel-related.
    location_hint is the raw LOCATION field from the calendar event, if any.
    It is passed as context but does not bypass travel classification.
    """
    user_content = (
        f"Event summary: {summary}\n"
        f"Location field: {location_hint or '(empty)'}\n"
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
