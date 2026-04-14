"""Thin MCP streamable-http client.

Handles session initialization and a single tool call.
Used by services that need to call MCP tools programmatically
(not via an LLM agent loop).
"""

from __future__ import annotations

import json
import httpx


def _parse_sse_json(text: str) -> dict:
    """Extract the JSON object from a text/event-stream response."""
    for line in text.splitlines():
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                return json.loads(payload)
    # Fall back: try parsing as plain JSON
    return json.loads(text)


def call_mcp(
    server_url: str,
    tool_name: str,
    arguments: dict,
    timeout: int = 20,
    auth_token: str = "",
) -> str:
    """Call an MCP tool via streamable-http.

    Returns the concatenated text content from the tool result.
    Raises RuntimeError on MCP-level errors.
    """
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    with httpx.Client(timeout=timeout) as client:
        init_resp = client.post(
            server_url,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "stack-service", "version": "1.0"},
                },
            },
        )
        init_resp.raise_for_status()
        session_id = init_resp.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("No mcp-session-id returned during initialize")

        session_headers = {**headers, "mcp-session-id": session_id}

        tool_resp = client.post(
            server_url,
            headers=session_headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        )
        tool_resp.raise_for_status()
        data = _parse_sse_json(tool_resp.text)

        error = data.get("error")
        if error:
            raise RuntimeError(f"MCP error: {error.get('message', error)}")

        content = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
