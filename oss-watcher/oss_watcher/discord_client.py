"""Fetch messages from a Discord channel via the user REST API."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from .config import DISCORD_CHANNEL_ID, DISCORD_TOKEN

log = logging.getLogger(__name__)

_BASE = "https://discord.com/api/v10"
_HEADERS = {"Authorization": DISCORD_TOKEN}
_PAGE_SIZE = 100


def fetch_messages(days: int = 7) -> list[dict]:
    """Return all messages from the last `days` days, oldest first."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    messages: list[dict] = []
    before: str | None = None

    with httpx.Client(headers=_HEADERS, timeout=30) as client:
        while True:
            params: dict = {"limit": _PAGE_SIZE}
            if before:
                params["before"] = before

            resp = client.get(f"{_BASE}/channels/{DISCORD_CHANNEL_ID}/messages", params=params)
            resp.raise_for_status()
            batch: list[dict] = resp.json()

            if not batch:
                break

            # Discord returns newest-first; stop when we go past our window
            filtered = [m for m in batch if datetime.fromisoformat(m["timestamp"].rstrip("Z")).replace(tzinfo=timezone.utc) >= since]
            messages.extend(filtered)

            if len(filtered) < len(batch):
                # Hit a message older than our window — done
                break

            before = batch[-1]["id"]

    # Return oldest-first
    messages.sort(key=lambda m: m["timestamp"])
    log.info("Fetched %d Discord messages from last %d days", len(messages), days)
    return messages


def format_transcript(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        ts = m["timestamp"][:16].replace("T", " ")
        author = m.get("author", {}).get("global_name") or m.get("author", {}).get("username", "unknown")
        content = m.get("content", "").strip()
        if content:
            lines.append(f"[{ts}] {author}: {content}")
    return "\n".join(lines)
