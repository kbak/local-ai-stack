"""Stock and financial data via local MCP proxy."""

from stack_shared.mcp_client import call_skill_mcp as call_mcp
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/finance/mcp"


def _call_mcp(tool_name: str, arguments: dict, timeout: int = 15) -> str:
    return call_mcp(MCP_URL, tool_name, arguments, timeout)


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
