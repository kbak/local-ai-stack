"""rss-watcher entry point — fires a news brief twice a day via APScheduler."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .briefer import run_news_brief

log = logging.getLogger(__name__)


async def _main() -> None:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_news_brief,
        trigger="cron",
        hour="0,12",
        minute=5,
        id="news_brief",
        replace_existing=True,
    )
    log.info("News brief scheduled at 00:05 and 12:05 UTC")
    scheduler.start()

    # Keep the process alive
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
