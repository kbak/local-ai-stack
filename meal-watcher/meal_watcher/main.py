"""meal-watcher entry point."""

from __future__ import annotations

import logging
import time

from .config import POLL_INTERVAL_MINUTES
from .poller import poll_once
from .state import load

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    log.info("Starting poll loop (interval=%dm)", POLL_INTERVAL_MINUTES)
    while True:
        log.info("Polling CalDAV...")
        try:
            poll_once()
        except Exception:
            log.exception("Poll loop error")
        time.sleep(POLL_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
