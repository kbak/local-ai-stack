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

# LLM — prefer LLM_* (signal-bot.env) with INFERENCE_* as fallback
INFERENCE_BASE_URL: str = os.environ.get("LLM_BASE_URL") or os.environ.get("INFERENCE_BASE_URL", "http://host.docker.internal:8080/v1")
INFERENCE_API_KEY: str = os.environ.get("LLM_API_KEY") or os.environ.get("INFERENCE_API_KEY", "sk-no-key-required")
INFERENCE_MODEL: str = os.environ.get("LLM_MODEL") or os.environ.get("INFERENCE_MODEL", "qwen")

SEARXNG_URL: str = os.environ.get("SEARXNG_URL", "http://searxng:8080")

# MCP endpoints — location-tracker requires auth, mcp-proxy does not
MCP_AUTH_TOKEN: str = os.environ.get("MCP_PROXY_AUTH_TOKEN", "")  # location-tracker only
MCP_PROXY_AUTH_TOKEN: str = ""  # mcp-proxy has no auth
MCP_PROXY_URL: str = os.environ.get("MCP_PROXY_URL", "http://mcp-proxy:8083")
LOCATION_TRACKER_URL: str = os.environ.get(
    "LOCATION_TRACKER_URL", "http://location-tracker:8084/mcp"
)

# Google Places API (New)
GOOGLE_MAPS_API_KEY: str = os.environ.get("GOOGLE_MAPS_API_KEY", "")

# Signal
SIGNAL_API_URL: str = os.environ.get("SIGNAL_API_URL", "http://signal-api:8080")
SIGNAL_NUMBER: str = os.environ["SIGNAL_NUMBER"]
CALENDAR_BRIEFING_RECIPIENT: str = os.environ["BRIEFING_RECIPIENT"]

STATE_FILE: str = os.environ.get("STATE_FILE", "/data/calendar_state.json")
