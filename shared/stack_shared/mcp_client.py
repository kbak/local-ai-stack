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


class MissingSessionError(RuntimeError):
    """The server did not return a session ID during initialization."""


def request_mcp(
    server_url: str,
    tool_name: str,
    arguments: dict,
    timeout: int = 20,
    auth_token: str = "",
    *,
    client_name: str = "stack-service",
    accept: str = "application/json, text/event-stream",
    initialized_notification: bool = False,
) -> dict:
    """Initialize a session and return one tool's JSON-RPC response.

    Some servers require an initialized notification or JSON-only negotiation.
    Callers retain their own handling of JSON-RPC and tool-result errors.
    """
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": accept,
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
                    "clientInfo": {"name": client_name, "version": "1.0"},
                },
            },
        )
        init_resp.raise_for_status()
        session_id = init_resp.headers.get("mcp-session-id")
        if not session_id:
            raise MissingSessionError("No mcp-session-id returned during initialize")

        session_headers = {**headers, "mcp-session-id": session_id}
        if initialized_notification:
            client.post(
                server_url,
                headers=session_headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )

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
        return _parse_sse_json(tool_resp.text)


def result_text(result: dict) -> str:
    """Join text blocks, leaving images and other result types to their callers."""
    return "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")


def call_mcp(
    server_url: str,
    tool_name: str,
    arguments: dict,
    timeout: int = 20,
    auth_token: str = "",
) -> str:
    """Return a tool's text content, raising on JSON-RPC errors."""
    data = request_mcp(server_url, tool_name, arguments, timeout, auth_token)
    error = data.get("error")
    if error:
        raise RuntimeError(f"MCP error: {error.get('message', error)}")
    return result_text(data.get("result", {}))


def call_skill_mcp(
    server_url: str,
    tool_name: str,
    arguments: dict,
    timeout: int = 15,
    *,
    initialized_notification: bool = False,
    check_tool_error: bool = False,
) -> str:
    """Use bot/voice protocol conventions and preserve their error messages."""
    # The direct PDF server needs SSE and an initialized notification; the
    # proxy-backed skills use JSON and call tools immediately after initialize.
    accept = "application/json, text/event-stream" if initialized_notification else "application/json"
    try:
        data = request_mcp(
            server_url, tool_name, arguments, timeout,
            client_name="signal-bot", accept=accept,
            initialized_notification=initialized_notification,
        )
    except MissingSessionError as exc:
        raise RuntimeError("No session ID returned") from exc
    if "error" in data:
        raise RuntimeError(data["error"].get("message", str(data["error"])))
    result = data.get("result", {})
    text = result_text(result)
    if check_tool_error and result.get("isError"):
        raise RuntimeError(text or f"MCP tool {tool_name} failed")
    return text
