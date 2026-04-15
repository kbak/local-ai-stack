import json
import os

# RSS feeds grouped by category: {"technology": ["url1", ...], "general": [...]}
RSS_FEEDS: dict[str, list[str]] = json.loads(os.environ.get("RSS_FEEDS", "{}"))

# How many hours back to include per run (matches brief cadence)
RSS_LOOKBACK_HOURS: int = int(os.environ.get("RSS_LOOKBACK_HOURS", "12"))

# LLM — shared with signal-bot.env naming
LLM_BASE_URL: str = os.environ.get("LLM_BASE_URL", "http://host.docker.internal:8080/v1")
LLM_API_KEY: str = os.environ.get("LLM_API_KEY", "sk-no-key-required")
LLM_MODEL: str = os.environ.get("LLM_MODEL", "qwen")

# Signal — shared with signal-bot.env
SIGNAL_API_URL: str = os.environ.get("SIGNAL_API_URL", "http://signal-api:8080")
SIGNAL_NUMBER: str = os.environ["SIGNAL_NUMBER"]
BRIEFING_RECIPIENT: str = os.environ["BRIEFING_RECIPIENT"]
