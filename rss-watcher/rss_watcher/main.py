"""rss-watcher entry point — fires a news brief twice a day via APScheduler."""

from __future__ import annotations

from stack_shared.cron_runner import run_cron

from .briefer import run_news_brief


def main() -> None:
    run_cron(
        run_news_brief,
        job_id="news_brief",
        log_message="News brief scheduled at 00:05 and 12:05 UTC",
        hour="0,12",
        minute=5,
    )


if __name__ == "__main__":
    main()
