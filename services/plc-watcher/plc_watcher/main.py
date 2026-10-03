"""plc-watcher entry point — daily Merkuriusz Rzeczypospolitej via APScheduler."""

from __future__ import annotations

from stack_shared.cron_runner import run_cron

from .briefer import run_plc_brief


def main() -> None:
    run_cron(
        run_plc_brief,
        job_id="plc_brief",
        log_message="Merkuriusz scheduled daily at 15:00 UTC (08:00 MST / 17:00 Warsaw)",
        hour=15,
        minute=0,
    )


if __name__ == "__main__":
    main()
