"""Fetch last N hours of Telegram messages and send a brief via Signal."""

from __future__ import annotations

import asyncio
import logging

from stack_shared.briefer import send_brief

from .config import SUMMARY_LOOKBACK_HOURS, TG_GROUP
from .fetcher import fetch_messages

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


async def _run() -> None:
    messages = await fetch_messages(SUMMARY_LOOKBACK_HOURS)
    if not messages:
        log.info("No messages in the last %dh — skipping brief", SUMMARY_LOOKBACK_HOURS)
        return

    transcript = "\n".join(f"[{m['date'][:16]}] {m['sender']}: {m['text']}" for m in messages)
    user_prompt = (
        f"Here are the last {SUMMARY_LOOKBACK_HOURS} hours of messages "
        f"from the Telegram group '{TG_GROUP}':\n\n{transcript}"
    )

    log.info("Summarising %d messages via LLM...", len(messages))
    send_brief("Telegram daily brief", _SYSTEM_PROMPT, user_prompt)


def run_summary() -> None:
    asyncio.run(_run())
