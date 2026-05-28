"""Image analysis and reverse search via the reverse-image-search MCP service.

analyze_image     — VLM describes image → SearXNG searches → VLM synthesizes.
                    Best for memes, photoshopped composites, or any image where
                    you want to understand what's happening / who's in it.

reverse_image_search — Yandex + SauceNAO visual fingerprint search.
                       Best for original, unmodified images that exist on the web.

Both tools accept either an HTTP/HTTPS URL or a local file path (e.g. a Signal
attachment stored under /signal-cli-data/attachments/).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
from strands import tool

_MCP_URL = "http://reverse-image-search:8091/mcp/"
_TIMEOUT = 120  # VLM chain can be slow on the first call


# ── MCP helper (inline — same pattern as pdf skill) ───────────────────────────

def _parse_mcp_body(resp: httpx.Response) -> dict:
    """Parse a FastMCP streamable-http response — either plain JSON or SSE-wrapped JSON."""
    ct = resp.headers.get("content-type", "")
    if "text/event-stream" in ct:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    return json.loads(payload)
        raise RuntimeError("No JSON found in SSE response")
    return resp.json()


def _call(tool_name: str, arguments: dict) -> str:
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    with httpx.Client(timeout=_TIMEOUT) as client:
        init = client.post(
            _MCP_URL,
            headers=headers,
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "signal-bot", "version": "1.0"},
                },
            },
        )
        init.raise_for_status()
        session_id = init.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("No mcp-session-id in initialize response")

        resp = client.post(
            _MCP_URL,
            headers={**headers, "mcp-session-id": session_id},
            json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        )
        resp.raise_for_status()
        data = _parse_mcp_body(resp)
        if "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        content = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


# ── Source resolution ─────────────────────────────────────────────────────────

def _is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def _read_as_b64(path: str) -> tuple[str, str]:
    """Read a local file and return (base64_string, filename)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return base64.b64encode(p.read_bytes()).decode(), p.name


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def analyze_image(source: str) -> str:
    """Identify people, objects, and memes in an image using AI vision + web search.

    Use this tool when:
    - The user sends an image or photo attachment
    - The user asks "who is this?", "what is this?", "explain this meme"
    - The image appears to be a meme, photoshop, or composite

    The tool sends the image to the local Qwen VLM which describes every element
    and generates search queries, executes those via SearXNG, then synthesizes
    a final answer — handling cases where even Google Lens would fail.

    Args:
        source: HTTP/HTTPS image URL, or absolute path to a local file
                (e.g. /signal-cli-data/attachments/some-image.jpg).
    """
    try:
        if _is_url(source):
            return _call("analyze_image", {"image_url": source})
        b64, filename = _read_as_b64(source)
        return _call("analyze_image_upload", {"image_base64": b64, "filename": filename})
    except Exception as exc:
        return f"Image analysis failed: {exc}"


@tool
def reverse_image_search(source: str) -> str:
    """Find where an image comes from on the web using Yandex Images and SauceNAO.

    Use this tool when:
    - The user asks "where is this image from?" or "find the source of this"
    - The image looks like an original, unmodified photo or artwork
    - You want to find similar images online

    Less effective for photoshopped composites or unique memes — use
    analyze_image for those instead.

    Args:
        source: HTTP/HTTPS image URL, or absolute path to a local file
                (e.g. /signal-cli-data/attachments/some-image.jpg).
    """
    try:
        if _is_url(source):
            return _call("reverse_image_search", {"image_url": source})
        b64, filename = _read_as_b64(source)
        return _call("reverse_image_search_upload", {"image_base64": b64, "filename": filename})
    except Exception as exc:
        return f"Reverse image search failed: {exc}"
