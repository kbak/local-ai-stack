"""calendar-watcher entry point."""

from __future__ import annotations

import logging
from stack_shared.polling import run_polling

from .config import POLL_INTERVAL_MINUTES
from .poller import poll_once

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    log.info("Starting poll loop (interval=%dm)", POLL_INTERVAL_MINUTES)
    run_polling(
        poll_once, POLL_INTERVAL_MINUTES * 60, logger=log,
        poll_message="Polling CalDAV...",
    )


if __name__ == "__main__":
    main()
