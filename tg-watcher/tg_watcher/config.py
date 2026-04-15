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

# SQLite DB for message storage
DB_PATH: str = os.environ.get("DB_PATH", "/data/messages.db")

# Summary schedule — cron fields (default: 5 AM MST = 12:00 UTC)
SUMMARY_CRON_HOUR: int = int(os.environ.get("SUMMARY_CRON_HOUR", "12"))
SUMMARY_CRON_MINUTE: int = int(os.environ.get("SUMMARY_CRON_MINUTE", "0"))

# How many hours back to include in the daily brief
SUMMARY_LOOKBACK_HOURS: int = int(os.environ.get("SUMMARY_LOOKBACK_HOURS", "24"))

# LLM
INFERENCE_BASE_URL: str = os.environ.get("INFERENCE_BASE_URL", "http://host.docker.internal:8080/v1")
INFERENCE_API_KEY: str = os.environ.get("INFERENCE_API_KEY", "sk-no-key-required")
INFERENCE_MODEL: str = os.environ.get("INFERENCE_MODEL", "qwen")

# Signal
SIGNAL_API_URL: str = os.environ.get("SIGNAL_API_URL", "http://signal-api:8080")
SIGNAL_NUMBER: str = os.environ["SIGNAL_NUMBER"]
BRIEFING_RECIPIENT: str = os.environ["BRIEFING_RECIPIENT"]
