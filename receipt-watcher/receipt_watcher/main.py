"""receipt-watcher entry point."""

from __future__ import annotations

import logging
from stack_shared.polling import run_polling

from .config import DRY_RUN, POLL_INTERVAL_MINUTES
from .poller import poll_once

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log.info("receipt-watcher starting (dry_run=%s, interval=%dm)", DRY_RUN, POLL_INTERVAL_MINUTES)
    run_polling(
        poll_once, POLL_INTERVAL_MINUTES * 60, logger=log,
    )


if __name__ == "__main__":
    main()
