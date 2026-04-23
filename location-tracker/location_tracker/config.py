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
LOCAL_TIMEZONE: str = os.environ.get("LOCAL_TIMEZONE", "America/Phoenix")

POLL_INTERVAL_MINUTES: int = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
LOOKBACK_DAYS: int = int(os.environ.get("LOOKBACK_DAYS", "30"))
LOOKAHEAD_DAYS: int = int(os.environ.get("LOOKAHEAD_DAYS", "90"))

# LLM base_url / api_key / model are resolved by stack_shared helpers at
# call time; no need to pin them here. See stack_shared/llm_model.py.

SEARXNG_URL: str = os.environ.get("SEARXNG_URL", "http://searxng:8080")

STATE_FILE: str = os.environ.get("STATE_FILE", "/data/location_state.json")

MCP_PORT: int = int(os.environ.get("MCP_PORT", "8084"))
MCP_AUTH_TOKEN: str = os.environ.get("MCP_PROXY_AUTH_TOKEN", "")
