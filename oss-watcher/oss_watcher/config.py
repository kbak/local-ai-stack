import os

# Discord user token + channel to monitor
DISCORD_TOKEN: str = os.environ["DISCORD_TOKEN"]
DISCORD_CHANNEL_ID: str = os.environ["DISCORD_CHANNEL_ID"]

# GitHub personal access token + repo to monitor (owner/repo)
GITHUB_TOKEN: str = os.environ["GITHUB_TOKEN"]
GITHUB_REPO: str = os.environ["GITHUB_REPO"]  # e.g. "owner/repo"

# Summary schedule — cron fields (default: Monday 08:00 UTC)
SUMMARY_CRON_DAY: str = os.environ.get("SUMMARY_CRON_DAY", "mon")
SUMMARY_CRON_HOUR: int = int(os.environ.get("SUMMARY_CRON_HOUR", "8"))
SUMMARY_CRON_MINUTE: int = int(os.environ.get("SUMMARY_CRON_MINUTE", "0"))

# LLM
INFERENCE_BASE_URL: str = os.environ.get("LLM_BASE_URL") or os.environ.get("INFERENCE_BASE_URL", "http://host.docker.internal:8080/v1")
INFERENCE_API_KEY: str = os.environ.get("LLM_API_KEY") or os.environ.get("INFERENCE_API_KEY", "sk-no-key-required")
INFERENCE_MODEL: str = os.environ.get("LLM_MODEL") or os.environ.get("INFERENCE_MODEL", "qwen")

# Signal
SIGNAL_API_URL: str = os.environ.get("SIGNAL_API_URL", "http://signal-api:8080")
SIGNAL_NUMBER: str = os.environ["SIGNAL_NUMBER"]
BRIEFING_RECIPIENT: str = os.environ["BRIEFING_RECIPIENT"]
