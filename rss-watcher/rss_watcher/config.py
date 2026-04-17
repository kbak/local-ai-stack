import json
import os

# RSS feeds grouped by category: {"technology": ["url1", ...], "general": [...]}
RSS_FEEDS: dict[str, list[str]] = json.loads(os.environ.get("RSS_FEEDS", "{}"))

# How many hours back to include per run (matches brief cadence)
RSS_LOOKBACK_HOURS: int = int(os.environ.get("RSS_LOOKBACK_HOURS", "12"))
