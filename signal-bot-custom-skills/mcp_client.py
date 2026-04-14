"""Shared MCP client that handles session initialization for streamable-http MCP servers."""

import httpx


def call_mcp(server_url: str, tool_name: str, arguments: dict, timeout: int = 20, auth_token: str = "") -> str:
    """Call an MCP tool via streamable-http, handling session initialization automatically."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    with httpx.Client(timeout=timeout) as client:
        # Step 1: initialize session
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
                    "clientInfo": {"name": "signal-bot", "version": "1.0"},
                },
            },
        )
        init_resp.raise_for_status()
        session_id = init_resp.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("No mcp-session-id returned during initialize")

        session_headers = {**headers, "mcp-session-id": session_id}

        # Step 2: call the tool
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
        data = tool_resp.json()

        error = data.get("error")
        if error:
            raise RuntimeError(f"MCP error: {error.get('message', error)}")

        content = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
