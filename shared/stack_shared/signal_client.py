"""Send messages via signal-api REST endpoint."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


def send_message(
    text: str,
    *,
    signal_api_url: str,
    signal_number: str,
    recipient: str,
) -> None:
    try:
        resp = httpx.post(
            f"{signal_api_url}/v2/send",
            json={
                "message": text,
                "number": signal_number,
                "recipients": [recipient],
            },
            timeout=15,
        )
        resp.raise_for_status()
        log.info("Signal message sent to %s", recipient)
    except Exception:
        log.exception("Failed to send Signal message")
        raise
