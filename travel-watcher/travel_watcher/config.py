from __future__ import annotations

import os

POLL_INTERVAL_MINUTES = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
INITIAL_LOOKBACK_HOURS = 168
IMAP_HOST = os.environ["TRAVEL_IMAP_HOST"]
IMAP_PORT = int(os.environ.get("TRAVEL_IMAP_PORT", "993"))
IMAP_USERNAME = os.environ["TRAVEL_IMAP_USERNAME"]
IMAP_PASSWORD = os.environ["TRAVEL_IMAP_PASSWORD"]
CALDAV_BASE_URL = os.environ["CALDAV_BASE_URL"]
CALDAV_USERNAME = os.environ["CALDAV_USERNAME"]
CALDAV_PASSWORD = os.environ["CALDAV_PASSWORD"]
CALENDAR_NAME = os.environ.get("TRAVEL_CALENDAR_NAME", "Travel")
PDF_MCP_URL = os.environ.get("PDF_MCP_URL", "http://pdf-inspector:8085/mcp/")
ATTACHMENT_DIR = "/travel-attachments"
STATE_FILE = "/data/travel_state.json"
AUDIT_FILE = "/data/travel.jsonl"
