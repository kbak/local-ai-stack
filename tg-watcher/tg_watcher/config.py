import os

# Telegram user account credentials (from https://my.telegram.org)
TG_API_ID: int = int(os.environ["TG_API_ID"])
TG_API_HASH: str = os.environ["TG_API_HASH"]
# Only needed for the first interactive login; ignored once session file exists
TG_PHONE: str | None = os.environ.get("TG_PHONE")

# Group to monitor — numeric ID (e.g. -1001234567890) or @username
TG_GROUP: str = os.environ["TG_GROUP"]

# Session file path (persisted in Docker volume)
TG_SESSION_FILE: str = os.environ.get("TG_SESSION_FILE", "/data/tg_session")

# Summary schedule — cron fields (default: 5 AM MST = 12:00 UTC)
SUMMARY_CRON_HOUR: int = int(os.environ.get("SUMMARY_CRON_HOUR", "12"))
SUMMARY_CRON_MINUTE: int = int(os.environ.get("SUMMARY_CRON_MINUTE", "0"))

# How many hours back to include in the daily brief
SUMMARY_LOOKBACK_HOURS: int = int(os.environ.get("SUMMARY_LOOKBACK_HOURS", "24"))

