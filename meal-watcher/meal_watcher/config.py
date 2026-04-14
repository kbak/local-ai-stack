import os

CALDAV_BASE_URL = os.environ["CALDAV_BASE_URL"]
CALDAV_USERNAME = os.environ["CALDAV_USERNAME"]
CALDAV_PASSWORD = os.environ["CALDAV_PASSWORD"]

CALENDAR_NAMES_RAW = os.environ.get("CALDAV_CALENDAR_NAMES", "")
CALENDAR_NAMES: list[str] = (
    [n.strip() for n in CALENDAR_NAMES_RAW.split(",") if n.strip()]
    if CALENDAR_NAMES_RAW.strip()
    else []
)

HOME_CITY: str = os.environ.get("HOME_CITY", "").strip()
LOCAL_TIMEZONE: str = os.environ.get("LOCAL_TIMEZONE", "America/Phoenix")

POLL_INTERVAL_MINUTES: int = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
LOOKAHEAD_DAYS: int = int(os.environ.get("LOOKAHEAD_DAYS", "90"))

INFERENCE_BASE_URL: str = os.environ.get(
    "INFERENCE_BASE_URL", "http://host.docker.internal:8080/v1"
)
INFERENCE_MODEL: str = os.environ.get("INFERENCE_MODEL", "qwen")
INFERENCE_API_KEY: str = os.environ.get("INFERENCE_API_KEY", "none")

SEARXNG_URL: str = os.environ.get("SEARXNG_URL", "http://searxng:8080")

# MCP endpoints
MCP_AUTH_TOKEN: str = os.environ.get("MCP_PROXY_AUTH_TOKEN", "")
MCP_PROXY_URL: str = os.environ.get("MCP_PROXY_URL", "http://mcp-proxy:8083")
LOCATION_TRACKER_URL: str = os.environ.get(
    "LOCATION_TRACKER_URL", "http://location-tracker:8084/mcp"
)

# Signal
SIGNAL_API_URL: str = os.environ.get("SIGNAL_API_URL", "http://signal-api:8080")
SIGNAL_NUMBER: str = os.environ["SIGNAL_NUMBER"]
# Recipient for meal briefings — must be set explicitly
MEAL_BRIEFING_RECIPIENT: str = os.environ["MEAL_BRIEFING_RECIPIENT"]

STATE_FILE: str = os.environ.get("STATE_FILE", "/data/meal_state.json")
