"""Fetch RSS items per category, summarize with LLM, send via Signal."""

from __future__ import annotations

import logging
import os

from stack_shared.llm_chat import chat
from stack_shared.signal_client import send_message

from .config import RSS_FEEDS, RSS_LOOKBACK_HOURS
from .fetcher import fetch_category

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a sharp news editor producing a brief for a busy reader. \
You will receive a list of RSS items from the last {hours} hours in the "{category}" category. \
Some items may be in languages other than English — translate them. \
Group related items by topic, remove near-duplicates, and write a concise English-language brief in plain text. \
Lead each topic with a short bold heading. Skip anything not substantive. \
Do not pad — if there is little news, say so briefly.\
"""


def run_news_brief() -> None:
    if not RSS_FEEDS:
        log.info("RSS_FEEDS is empty — skipping news brief")
        return

    base_url = os.environ.get("LLM_BASE_URL", "http://host.docker.internal:8080/v1")
    api_key = os.environ.get("LLM_API_KEY", "sk-no-key-required")
    model = os.environ.get("LLM_MODEL", "qwen")

    parts: list[str] = []

    for category, urls in RSS_FEEDS.items():
        items = fetch_category(urls, RSS_LOOKBACK_HOURS)
        if not items:
            log.info("No recent items for category '%s'", category)
            continue

        digest = "\n\n".join(
            f"[{it['source']}] {it['title']}\n{it['link']}\n{it['summary']}"
            for it in items
        )
        user_prompt = (
            f"Here are {len(items)} RSS items from the last {RSS_LOOKBACK_HOURS} hours "
            f"in the '{category}' category:\n\n{digest}"
        )

        log.info("Summarising %d items for category '%s'...", len(items), category)
        summary = chat(
            _SYSTEM_PROMPT.format(hours=RSS_LOOKBACK_HOURS, category=category),
            user_prompt,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )
        parts.append(f"*{category.upper()}*\n{summary}")

    if not parts:
        log.info("No news items across all categories — skipping signal message")
        return

    send_message(
        "*RSS News Brief*\n\n" + "\n\n---\n\n".join(parts),
        signal_api_url=os.environ.get("SIGNAL_API_URL", "http://signal-api:8080"),
        signal_number=os.environ["SIGNAL_NUMBER"],
        recipient=os.environ["BRIEFING_RECIPIENT"],
    )
    log.info("News brief sent.")
