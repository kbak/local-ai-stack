"""Send messages via signal-api REST endpoint."""

from __future__ import annotations

import logging

import httpx

from .config import BRIEFING_RECIPIENT, SIGNAL_API_URL, SIGNAL_NUMBER

log = logging.getLogger(__name__)


def send_message(text: str) -> None:
    try:
        resp = httpx.post(
            f"{SIGNAL_API_URL}/v2/send",
            json={
                "message": text,
                "number": SIGNAL_NUMBER,
                "recipients": [BRIEFING_RECIPIENT],
            },
            timeout=15,
        )
        resp.raise_for_status()
        log.info("Signal message sent to %s", BRIEFING_RECIPIENT)
    except Exception:
        log.exception("Failed to send Signal message")
        raise
