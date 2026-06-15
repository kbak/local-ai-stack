"""PDF reading and text extraction via local MCP proxy."""

import json

import httpx
from strands import tool

# Trailing slash is required: FastMCP mounts the streamable-http app at /mcp/, and a
# POST to /mcp without it gets a 307 redirect that httpx won't follow.
MCP_URL = "http://pdf-inspector:8085/mcp/"
# Streamable-http requires the client to accept SSE; responses come back as
# `event: message\ndata: {json}` rather than a plain JSON body.
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _parse_sse(text: str) -> dict:
    """Pull the JSON-RPC payload out of an SSE response body."""
    for line in text.splitlines():
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                return json.loads(payload)
    # Fall back to a plain JSON body if the server didn't use SSE.
    return json.loads(text)


def _call_mcp(tool_name: str, arguments: dict, timeout: int = 120) -> str:
    with httpx.Client(timeout=timeout) as client:
        init = client.post(MCP_URL, headers=_HEADERS, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "signal-bot", "version": "1.0"}},
        })
        init.raise_for_status()
        session_id = init.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("No session ID returned")
        sess = {**_HEADERS, "mcp-session-id": session_id}
        # FastMCP expects the initialized notification before any tools/call.
        client.post(MCP_URL, headers=sess, json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        resp = client.post(MCP_URL, headers=sess, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        resp.raise_for_status()
        data = _parse_sse(resp.text)
        if "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        content = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


@tool
def read_pdf(source: str) -> str:
    """Extract text from a PDF file given a URL or file path.

    Use when the user shares a PDF link or asks to read/summarize a PDF document.

    Args:
        source: URL or file path to the PDF.
    """
    try:
        return _call_mcp("read_pdf", {"source": source})
    except Exception as e:
        return f"PDF read failed: {e}"
