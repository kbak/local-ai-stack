"""Readable, bounded web excerpts without raw HTML or pagination prompts."""

import logging
import subprocess
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp_server_fetch.server import (
    DEFAULT_USER_AGENT_AUTONOMOUS,
    check_may_autonomously_fetch_url,
    fetch_url,
)
from pydantic import AnyHttpUrl, Field


mcp = FastMCP("fetch")
MAX_EXCERPT_LENGTH = 5000
logger = logging.getLogger(__name__)


@mcp.tool()
async def fetch(
    url: AnyHttpUrl,
    max_length: Annotated[int, Field(ge=1)] = 4000,
    start_index: Annotated[int, Field(ge=0)] = 0,
) -> dict:
    """Read a webpage as a compact text excerpt, with HTML simplified to Markdown.

    Fetch only when information needed for the answer is missing from search
    results, or the user asks to read a page. Normally read at most one page for
    a simple lookup. Reuse excerpts already in the conversation. Truncation is
    informational: continue at start_index only if the missing text is needed
    to answer the question. max_length is capped at 5000 characters.
    """
    source = str(url)
    await check_may_autonomously_fetch_url(source, DEFAULT_USER_AGENT_AUTONOMOUS)
    try:
        content, _ = await fetch_url(source, DEFAULT_USER_AGENT_AUTONOMOUS, force_raw=False)
    except subprocess.CalledProcessError as error:
        logger.warning("HTML extraction failed for %s (exit %s)", source, error.returncode)
        return {
            "url": source,
            "error": "Readable text could not be extracted from this page. Use another source or the search excerpt.",
            "retryable": False,
        }
    excerpt = content[start_index : start_index + min(max_length, MAX_EXCERPT_LENGTH)]
    end_index = start_index + len(excerpt)
    truncated = end_index < len(content)
    result = {
        "url": source,
        "content": excerpt,
        "start_index": start_index,
        "end_index": end_index,
        "total_characters": len(content),
        "truncated": truncated,
    }
    if truncated:
        result["next_start_index"] = end_index
    return result


if __name__ == "__main__":
    mcp.run()
