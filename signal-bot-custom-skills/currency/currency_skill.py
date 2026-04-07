"""Currency conversion and exchange rates via local MCP proxy."""

import httpx
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/currency/mcp"


def _call_mcp(tool_name: str, arguments: dict, timeout: int = 15) -> str:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        init = client.post(MCP_URL, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "signal-bot", "version": "1.0"}}})
        init.raise_for_status()
        session_id = init.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("No session ID returned")
        resp = client.post(MCP_URL, headers={**headers, "mcp-session-id": session_id}, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}})
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        content = data.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


@tool
def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    """Convert an amount from one currency to another using live exchange rates.

    Use when the user asks to convert money between currencies (e.g. '100 USD to EUR').

    Args:
        amount: The amount to convert.
        from_currency: Source currency code (e.g. 'USD', 'EUR', 'PLN').
        to_currency: Target currency code (e.g. 'GBP', 'JPY').
    """
    try:
        return _call_mcp("convert_currency_latest", {"amount": amount, "from_currency": from_currency, "to_currency": to_currency})
    except Exception as e:
        return f"Currency conversion failed: {e}"


@tool
def get_exchange_rates(base_currency: str = "USD") -> str:
    """Get latest exchange rates for a base currency.

    Use when the user asks about exchange rates or the value of a currency.

    Args:
        base_currency: Base currency code (e.g. 'USD', 'EUR').
    """
    try:
        return _call_mcp("get_latest_exchange_rates", {"base_currency": base_currency})
    except Exception as e:
        return f"Exchange rates fetch failed: {e}"
