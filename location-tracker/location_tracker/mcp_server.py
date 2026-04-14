"""FastMCP server exposing get_location_at tool."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone

from fastmcp import FastMCP

from .config import MCP_PORT, POLL_INTERVAL_MINUTES
from .poller import poll_once
from .state import State, load
from .timeline import build_spans, get_location_at as _get_location_at

log = logging.getLogger(__name__)

mcp = FastMCP("location-tracker")

# Shared state — updated by background poller, read by MCP tool
_state: State = State(anchors={}, spans=[])
_state_lock = threading.Lock()


@mcp.tool()
def get_location_at(datetime_iso: str) -> dict:
    """
    Return the user's city at the given ISO 8601 datetime.

    Returns: {city: str, confidence: "high"|"medium"|"low"|"explicit"|"fallback", source: str}
    """
    try:
        dt = datetime.fromisoformat(datetime_iso)
    except ValueError:
        return {"error": f"Invalid datetime: {datetime_iso}"}

    with _state_lock:
        spans = list(_state.spans)

    return _get_location_at(dt, spans)


def _poll_loop() -> None:
    global _state
    log.info("Starting poll loop (interval=%dm)", POLL_INTERVAL_MINUTES)
    while True:
        log.info("Polling CalDAV...")
        try:
            new_state = poll_once()
            with _state_lock:
                _state = new_state
        except Exception:
            log.exception("Poll loop error")
        import time
        time.sleep(POLL_INTERVAL_MINUTES * 60)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Load existing state immediately so tool is useful before first poll completes
    global _state
    _state = load()
    if not _state.spans and _state.anchors:
        # Recompute spans for state files written before this refactor
        _state.spans = build_spans(_state.anchors)

    # Start background poller thread
    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()

    log.info("Starting MCP server on port %d", MCP_PORT)
    mcp.run(transport="streamable-http", host="0.0.0.0", port=MCP_PORT, path="/mcp")


if __name__ == "__main__":
    main()
