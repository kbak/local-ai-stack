"""Sequential polling with a delay after each completed or failed attempt."""

from collections.abc import Callable
import logging
import time


def run_polling(
    poll: Callable[[], object],
    interval_seconds: float,
    *,
    logger: logging.Logger,
    error_message: str = 'Poll loop error',
    poll_message: str | None = None,
) -> None:
    """Poll immediately, log ordinary failures, and let shutdown signals escape."""
    while True:
        if poll_message:
            logger.info(poll_message)
        try:
            poll()
        except Exception:
            logger.exception(error_message)
        time.sleep(interval_seconds)
