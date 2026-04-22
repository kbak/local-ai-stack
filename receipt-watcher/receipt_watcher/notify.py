"""Signal notifications — thin wrapper over stack_shared.signal_client."""

from __future__ import annotations

import logging

from stack_shared.signal_client import send_message as _send

from .config import BRIEFING_RECIPIENT, SIGNAL_API_URL, SIGNAL_NUMBER

log = logging.getLogger(__name__)


def notify(text: str) -> None:
    if not SIGNAL_NUMBER or not BRIEFING_RECIPIENT:
        log.warning("Signal not configured (SIGNAL_NUMBER / BRIEFING_RECIPIENT missing) — not sending: %s", text)
        return
    try:
        _send(
            text,
            signal_api_url=SIGNAL_API_URL,
            signal_number=SIGNAL_NUMBER,
            recipient=BRIEFING_RECIPIENT,
        )
    except Exception:
        log.exception("Signal send failed: %s", text)
