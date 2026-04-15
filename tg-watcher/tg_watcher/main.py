"""tg-watcher entry point.

Runs two things concurrently:
  1. Telethon listener — streams new messages into SQLite.
  2. APScheduler cron — fires daily summary at the configured UTC time.
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import SUMMARY_CRON_HOUR, SUMMARY_CRON_MINUTE
from .listener import run_listener
from .summarizer import run_summary

log = logging.getLogger(__name__)


def _schedule_summary(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(
        run_summary,
        trigger="cron",
        hour=SUMMARY_CRON_HOUR,
        minute=SUMMARY_CRON_MINUTE,
        id="daily_brief",
        replace_existing=True,
    )
    log.info(
        "Daily brief scheduled at %02d:%02d UTC", SUMMARY_CRON_HOUR, SUMMARY_CRON_MINUTE
    )


async def _main() -> None:
    scheduler = AsyncIOScheduler()
    _schedule_summary(scheduler)
    scheduler.start()

    await run_listener()  # blocks until disconnected


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_main())


if __name__ == "__main__":
    main()
