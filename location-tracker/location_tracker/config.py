import os

CALDAV_BASE_URL = os.environ["CALDAV_BASE_URL"]
CALDAV_USERNAME = os.environ["CALDAV_USERNAME"]
CALDAV_PASSWORD = os.environ["CALDAV_PASSWORD"]

# Comma-separated calendar display names to track; empty = all calendars
CALENDAR_NAMES_RAW = os.environ.get("CALDAV_CALENDAR_NAMES", "")
CALENDAR_NAMES: list[str] = (
    [n.strip() for n in CALENDAR_NAMES_RAW.split(",") if n.strip()]
    if CALENDAR_NAMES_RAW.strip()
    else []
)

HOME_CITY: str = os.environ.get("HOME_CITY", "").strip()

POLL_INTERVAL_MINUTES: int = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
LOOKBACK_DAYS: int = int(os.environ.get("LOOKBACK_DAYS", "30"))
LOOKAHEAD_DAYS: int = int(os.environ.get("LOOKAHEAD_DAYS", "90"))

INFERENCE_BASE_URL: str = os.environ.get(
    "INFERENCE_BASE_URL", "http://host.docker.internal:8080/v1"
)
INFERENCE_MODEL: str = os.environ.get("INFERENCE_MODEL", "qwen")
INFERENCE_API_KEY: str = os.environ.get("INFERENCE_API_KEY", "none")

SEARXNG_URL: str = os.environ.get("SEARXNG_URL", "http://searxng:8080")

STATE_FILE: str = os.environ.get("STATE_FILE", "/data/location_state.json")

MCP_PORT: int = int(os.environ.get("MCP_PORT", "8084"))
