from __future__ import annotations

import logging
import time

from .config import POLL_INTERVAL_MINUTES
from .poller import poll_once


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.info("travel-watcher starting (interval=%dm)", POLL_INTERVAL_MINUTES)
    while True:
        try:
            poll_once()
        except Exception:
            logging.exception("Poll cycle failed")
        time.sleep(POLL_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
