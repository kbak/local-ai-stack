from __future__ import annotations

import logging
from stack_shared.polling import run_polling

from .config import POLL_INTERVAL_MINUTES
from .poller import poll_once


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.info("travel-watcher starting (interval=%dm)", POLL_INTERVAL_MINUTES)
    run_polling(
        poll_once, POLL_INTERVAL_MINUTES * 60, logger=logging.getLogger(),
        error_message="Poll cycle failed",
    )


if __name__ == "__main__":
    main()
