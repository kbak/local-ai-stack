import os

# Discord user token + channel to monitor (both optional — omit to skip Discord)
DISCORD_TOKEN: str | None = os.environ.get("DISCORD_TOKEN")
DISCORD_CHANNEL_ID: str | None = os.environ.get("DISCORD_CHANNEL_ID")

# GitHub personal access token + repo to monitor (owner/repo)
GITHUB_TOKEN: str = os.environ["GITHUB_TOKEN"]
GITHUB_REPO: str = os.environ["GITHUB_REPO"]  # e.g. "owner/repo"

# Summary schedule — cron fields (default: Monday 08:00 UTC)
SUMMARY_CRON_DAY: str = os.environ.get("SUMMARY_CRON_DAY", "mon")
SUMMARY_CRON_HOUR: int = int(os.environ.get("SUMMARY_CRON_HOUR", "8"))
SUMMARY_CRON_MINUTE: int = int(os.environ.get("SUMMARY_CRON_MINUTE", "0"))

