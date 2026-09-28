"""Schedule daily RSS news and an optional weekly blog brief in one process."""

from __future__ import annotations

import os

from stack_shared.cron_runner import run_cron

from .briefer import run_news_brief


def main() -> None:
    extra_jobs = ()
    if os.environ.get("BLOG_SOURCES_FILE"):
        from .blogs import run_blog_brief
        extra_jobs = ((run_blog_brief, "blog_brief", {
            "day_of_week": "tue", "hour": 10, "minute": 0,
            "timezone": os.environ.get("BLOG_TIMEZONE", "America/Phoenix"),
        }),)
    run_cron(
        run_news_brief,
        job_id="news_brief",
        log_message="News brief scheduled at 00:05 and 12:05 UTC",
        hour="0,12",
        minute=5,
        timezone="UTC",
        extra_jobs=extra_jobs,
    )


if __name__ == "__main__":
    main()
