"""Currency conversion and exchange rates via local MCP proxy."""

from stack_shared.mcp_client import call_skill_mcp as call_mcp
from strands import tool

MCP_URL = "http://mcp-proxy:8083/servers/currency/mcp"


def _call_mcp(tool_name: str, arguments: dict, timeout: int = 15) -> str:
    return call_mcp(MCP_URL, tool_name, arguments, timeout)


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
