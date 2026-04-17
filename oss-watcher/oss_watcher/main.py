"""oss-watcher entry point — weekly OSS summary via APScheduler."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import SUMMARY_CRON_DAY, SUMMARY_CRON_HOUR, SUMMARY_CRON_MINUTE
from .summarizer import run_summary

log = logging.getLogger(__name__)


async def _main() -> None:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_summary,
        trigger="cron",
        day_of_week=SUMMARY_CRON_DAY,
        hour=SUMMARY_CRON_HOUR,
        minute=SUMMARY_CRON_MINUTE,
        id="weekly_brief",
        replace_existing=True,
    )
    log.info(
        "Weekly brief scheduled: %s at %02d:%02d UTC",
        SUMMARY_CRON_DAY.upper(),
        SUMMARY_CRON_HOUR,
        SUMMARY_CRON_MINUTE,
    )
    scheduler.start()

    # Keep alive
    while True:
        await asyncio.sleep(3600)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_main())


if __name__ == "__main__":
    main()
