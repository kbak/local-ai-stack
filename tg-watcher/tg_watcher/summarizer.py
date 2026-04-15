"""Pull last N hours of messages, ask LLM to summarize, send via Signal."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from openai import OpenAI

from .config import (
    INFERENCE_API_KEY,
    INFERENCE_BASE_URL,
    INFERENCE_MODEL,
    SUMMARY_LOOKBACK_HOURS,
    TG_GROUP,
)
from .db import fetch_since, prune_older_than
from .signal_client import send_message

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a concise security intelligence analyst. The user will give you a transcript \
of messages from a large Telegram group of crypto and blockchain security professionals \
(researchers, auditors, engineers from many different projects and companies). \
Produce a clear daily brief in plain text covering:
- Notable security incidents, exploits, or vulnerabilities discussed
- Interesting tools, techniques, or research shared
- Important links and what they are about
- Any significant debates or differing opinions
Skip noise, price talk, and generic chatter. Do not invent action items or decisions — \
this is an information-sharing community, not a team. Be concise but capture anything \
a security professional would find valuable.\
"""


def run_summary() -> None:
    since = datetime.now(timezone.utc) - timedelta(hours=SUMMARY_LOOKBACK_HOURS)
    messages = fetch_since(since)

    if not messages:
        log.info("No messages in the last %dh — skipping brief", SUMMARY_LOOKBACK_HOURS)
        return

    transcript = "\n".join(
        f"[{m['date'][:16]}] {m['sender']}: {m['text']}" for m in messages
    )
    user_prompt = (
        f"Here are the last {SUMMARY_LOOKBACK_HOURS} hours of messages "
        f"from the Telegram group '{TG_GROUP}':\n\n{transcript}"
    )

    log.info("Summarising %d messages via LLM...", len(messages))
    client = OpenAI(base_url=INFERENCE_BASE_URL, api_key=INFERENCE_API_KEY)
    response = client.chat.completions.create(
        model=INFERENCE_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )
    summary = (response.choices[0].message.content or "").strip()

    brief = f"*Telegram daily brief*\n\n{summary}"
    send_message(brief)

    # Keep DB tidy — drop anything older than 48h
    prune_older_than(datetime.now(timezone.utc) - timedelta(hours=48))
    log.info("Brief sent and old messages pruned.")
