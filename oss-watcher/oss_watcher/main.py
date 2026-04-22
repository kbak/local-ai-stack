"""oss-watcher entry point — weekly OSS summary via APScheduler."""

from __future__ import annotations

from stack_shared.cron_runner import run_cron

from .config import SUMMARY_CRON_DAY, SUMMARY_CRON_HOUR, SUMMARY_CRON_MINUTE
from .summarizer import run_summary


def main() -> None:
    run_cron(
        run_summary,
        job_id="weekly_brief",
        log_message=(
            f"Weekly brief scheduled: {SUMMARY_CRON_DAY.upper()} "
            f"at {SUMMARY_CRON_HOUR:02d}:{SUMMARY_CRON_MINUTE:02d} UTC"
        ),
        day_of_week=SUMMARY_CRON_DAY,
        hour=SUMMARY_CRON_HOUR,
        minute=SUMMARY_CRON_MINUTE,
    )


if __name__ == "__main__":
    main()
