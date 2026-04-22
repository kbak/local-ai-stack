"""tg-watcher entry point — daily Telegram summary via APScheduler."""

from __future__ import annotations

from stack_shared.cron_runner import run_cron

from .config import SUMMARY_CRON_HOUR, SUMMARY_CRON_MINUTE
from .summarizer import run_summary


def main() -> None:
    run_cron(
        run_summary,
        job_id="daily_brief",
        log_message=(
            f"Daily brief scheduled at {SUMMARY_CRON_HOUR:02d}:{SUMMARY_CRON_MINUTE:02d} UTC"
        ),
        hour=SUMMARY_CRON_HOUR,
        minute=SUMMARY_CRON_MINUTE,
    )


if __name__ == "__main__":
    main()
