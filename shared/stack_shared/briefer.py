"""Send a titled LLM-generated brief over Signal."""

from __future__ import annotations

import logging
import os

from .llm_chat import chat
from .signal_client import send_message
from .voice_note import send_text_and_voice_brief

log = logging.getLogger(__name__)


def send_brief(
    title: str,
    system_prompt: str,
    user_prompt: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    signal_api_url: str | None = None,
    signal_number: str | None = None,
    recipient: str | None = None,
) -> None:
    # LLM base_url/api_key/model all resolve inside chat() when None -
    # explicit args here are just overrides for callers that need them.
    summary = chat(
        system_prompt,
        user_prompt,
        base_url=base_url,
        api_key=api_key,
        model=model,
    )
    body = f"*{title}*\n\n{summary}"

    signal_api_url = signal_api_url or os.environ.get("SIGNAL_API_URL", "http://signal-api:8080")
    signal_number = signal_number or os.environ["SIGNAL_NUMBER"]
    recipient = recipient or os.environ["BRIEFING_RECIPIENT"]

    if os.environ.get("SIGNAL_VOICE_BRIEF") == "1":
        send_text_and_voice_brief(
            body,
            signal_api_url=signal_api_url,
            signal_number=signal_number,
            recipient=recipient,
        )
    else:
        send_message(body, signal_api_url=signal_api_url, signal_number=signal_number, recipient=recipient)
    log.info("Brief '%s' sent.", title)
