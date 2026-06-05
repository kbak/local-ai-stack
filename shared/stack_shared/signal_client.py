"""Send messages via signal-api REST endpoint."""

from __future__ import annotations

import base64
import logging

import httpx

log = logging.getLogger(__name__)


def send_message(
    text: str,
    *,
    signal_api_url: str,
    signal_number: str,
    recipient: str,
    image_png: bytes | None = None,
) -> None:
    """Send a text message, optionally with a PNG attachment.

    `recipient` may be a phone number or a `group.<id>` identifier.
    """
    payload: dict = {
        "message": text,
        "number": signal_number,
        "recipients": [recipient],
    }
    if image_png is not None:
        encoded = base64.standard_b64encode(image_png).decode()
        payload["base64_attachments"] = [
            f"data:image/png;filename=image.png;base64,{encoded}"
        ]
    try:
        resp = httpx.post(
            f"{signal_api_url}/v2/send",
            json=payload,
            timeout=60 if image_png else 15,
        )
        if not resp.is_success:
            log.error("signal-api %s: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        log.info("Signal message sent to %s", recipient)
    except Exception:
        log.exception("Failed to send Signal message")
        raise
