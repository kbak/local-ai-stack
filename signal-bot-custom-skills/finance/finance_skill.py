"""Stock and financial data via local MCP proxy."""

import httpx
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/finance/mcp"


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
def get_stock_info(ticker: str) -> str:
    """Get current stock price and key information for a ticker symbol.

    Use when the user asks about a stock price, company financials, or market data.

    Args:
        ticker: Stock ticker symbol (e.g. 'AAPL', 'TSLA', 'NVDA').
    """
    try:
        return _call_mcp("get_stock_info", {"ticker": ticker})
    except Exception as e:
        return f"Stock info fetch failed: {e}"


@tool
def get_stock_history(ticker: str, period: str = "1mo") -> str:
    """Get historical price data for a stock.

    Use when the user asks about a stock's price history or performance over time.

    Args:
        ticker: Stock ticker symbol.
        period: Time period - '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y'.
    """
    try:
        return _call_mcp("get_stock_history", {"ticker": ticker, "period": period})
    except Exception as e:
        return f"Stock history fetch failed: {e}"


@tool
def search_stocks(query: str) -> str:
    """Search for stocks by company name or keyword.

    Use when the user knows the company name but not the ticker symbol.

    Args:
        query: Company name or keyword to search for.
    """
    try:
        return _call_mcp("search_stocks", {"query": query})
    except Exception as e:
        return f"Stock search failed: {e}"
