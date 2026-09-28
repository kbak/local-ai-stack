"""Run an async job on a cron schedule and block forever.

Collapses the boilerplate shared by oss-watcher, rss-watcher, and tg-watcher:
configure logging, build an AsyncIOScheduler with one cron job, start it, and
keep the event loop alive.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler


def run_cron(
    job: Callable[[], object],
    *,
    job_id: str,
    log_message: str,
    extra_jobs: tuple[tuple[Callable[[], object], str, dict], ...] = (),
    **cron_kwargs,
) -> None:
    """Schedule `job` on a cron trigger and run forever.

    `cron_kwargs` are passed straight through to APScheduler's cron trigger
    (e.g. `hour="0,12"`, `minute=5`, `day_of_week="mon"`).
    `extra_jobs` adds independent (callable, id, cron kwargs) schedules to the
    same process without duplicating scheduler/event-loop setup.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger(job_id)

    async def _main() -> None:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            job,
            trigger="cron",
            id=job_id,
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
            **cron_kwargs,
        )
        for extra_job, extra_id, schedule in extra_jobs:
            scheduler.add_job(
                extra_job, trigger="cron", id=extra_id,
                replace_existing=True, misfire_grace_time=3600,
                coalesce=True, max_instances=1, **schedule,
            )
            log.info("Scheduled %s: %s", extra_id, schedule)
        log.info(log_message)
        scheduler.start()
        while True:
            await asyncio.sleep(3600)

    asyncio.run(_main())
