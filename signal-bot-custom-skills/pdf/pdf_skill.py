"""PDF reading and text extraction via local MCP proxy."""

from stack_shared.mcp_client import call_skill_mcp as call_mcp
from strands import tool

# Trailing slash is required: FastMCP mounts the streamable-http app at /mcp/, and a
# POST to /mcp without it gets a 307 redirect that httpx won't follow.
MCP_URL = "http://pdf-inspector:8085/mcp/"


def _call_mcp(tool_name: str, arguments: dict, timeout: int = 120) -> str:
    return call_mcp(MCP_URL, tool_name, arguments, timeout, initialized_notification=True)


@tool
def read_pdf(source: str) -> str:
    """Extract text from a PDF file given a URL or file path.

    Use only when the user shares a genuine PDF or asks to read/summarize one.
    Never use this tool for audio, images, arbitrary files, or existence checks.

    Args:
        source: URL or file path to the PDF.
    """
    try:
        return _call_mcp("read_pdf", {"source": source})
    except Exception as e:
        return f"PDF read failed: {e}"
