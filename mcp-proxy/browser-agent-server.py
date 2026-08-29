"""MCP facade for the asynchronous browser-agent REST service."""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("browser-agent")
API_URL = os.environ.get("BROWSER_AGENT_API_URL", "http://browser-agent-api:8092").rstrip("/")
API_TOKEN = os.environ.get("BROWSER_AGENT_API_TOKEN", "")
DEFAULT_TIMEOUT_SECONDS = 600


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    request = Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"browser-agent returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"browser-agent is unavailable: {exc.reason}") from exc


def _task_payload(
    task: str,
    start_url: str | None,
    allowed_domains: list[str] | None,
    max_steps: int,
    image_prompt: str | None,
    max_images: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task": task,
        "max_steps": max(1, min(max_steps, 100)),
        "use_vision": False,
    }
    if start_url:
        payload["start_url"] = start_url
    if allowed_domains:
        payload["allowed_domains"] = allowed_domains
    if image_prompt:
        payload["image_analysis"] = {
            "prompt": image_prompt,
            "max_images": max(1, min(max_images, 100)),
            "batch_size": 4,
        }
    return payload


def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: result.get(key)
        for key in (
            "id",
            "status",
            "result",
            "final_text",
            "urls",
            "image_assets",
            "image_analysis_summary",
            "errors",
            "duration_seconds",
            "partial",
        )
        if result.get(key) not in (None, [], "")
    }
    if result.get("image_assets"):
        compact["image_count"] = len(result["image_assets"])
    # Avoid duplicating a large batch payload once a merged answer exists.
    # If merging failed, retain the batch reports as fallback evidence.
    if result.get("image_analysis") and not result.get("image_analysis_summary"):
        compact["image_analysis"] = result["image_analysis"]
    return compact


@mcp.tool()
def browser_use(
    task: str,
    start_url: str | None = None,
    allowed_domains: list[str] | None = None,
    image_prompt: str | None = None,
    max_steps: int = 20,
    max_images: int = 20,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Use an expensive headless browser fallback and wait for the result.

    Use this only when the request requires interaction, JavaScript rendering,
    bot-protection handling, or opening a page gallery. Do not use it for ordinary
    web searches, market research, comparisons, or fetching readable articles;
    use web_search and fetch for those. Reuse browser results already present in
    the conversation instead of reopening the same page. Give a concrete task and
    normally provide `start_url`. Use `allowed_domains` to constrain navigation.
    For product, vehicle, property, or other photo-heavy pages, set `image_prompt`;
    the service extracts original assets and inspects them with Qwen vision.
    The returned `image_analysis_summary` is the completed visual assessment;
    answer from it directly and do not send its URLs to another image tool.
    This tool can take several minutes on protected or image-heavy sites.
    """
    accepted = _request(
        "POST",
        "/v1/tasks",
        _task_payload(task, start_url, allowed_domains, max_steps, image_prompt, max_images),
    )
    task_id = accepted["id"]
    deadline = time.monotonic() + max(10, min(timeout_seconds, 900))
    while time.monotonic() < deadline:
        result = _request("GET", f"/v1/tasks/{task_id}")
        if result.get("status") in {"completed", "failed"}:
            return _compact_result(result)
        time.sleep(2)
    return {
        "id": task_id,
        "status": "running",
        "message": "MCP wait timed out; call get_browser_task with this id for the eventual result.",
    }


@mcp.tool()
def submit_browser_task(
    task: str,
    start_url: str | None = None,
    allowed_domains: list[str] | None = None,
    image_prompt: str | None = None,
    max_steps: int = 20,
    max_images: int = 20,
) -> dict[str, Any]:
    """Start a headless browser job without waiting; returns a task id."""
    return _request(
        "POST",
        "/v1/tasks",
        _task_payload(task, start_url, allowed_domains, max_steps, image_prompt, max_images),
    )


@mcp.tool()
def get_browser_task(task_id: str) -> dict[str, Any]:
    """Get status and available results for a browser task id."""
    return _compact_result(_request("GET", f"/v1/tasks/{task_id}"))


if __name__ == "__main__":
    mcp.run()
