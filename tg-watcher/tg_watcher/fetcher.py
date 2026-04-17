"""Fetch recent messages from a Telegram group via Telethon history API."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.tl.types import User

from .config import TG_API_ID, TG_API_HASH, TG_GROUP, TG_SESSION_FILE

log = logging.getLogger(__name__)


async def fetch_messages(hours: int) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    messages: list[dict] = []

    async with TelegramClient(TG_SESSION_FILE, TG_API_ID, TG_API_HASH) as client:
        entity = await client.get_entity(TG_GROUP)
        log.info("Fetching last %dh from '%s'", hours, getattr(entity, "title", TG_GROUP))

        async for msg in client.iter_messages(entity, offset_date=None, reverse=False):
            if msg.date.replace(tzinfo=timezone.utc) < since:
                break
            if not msg.text or not msg.text.strip():
                continue
            sender_name = "unknown"
            try:
                sender = await msg.get_sender()
                if isinstance(sender, User):
                    parts = [sender.first_name or "", sender.last_name or ""]
                    sender_name = " ".join(p for p in parts if p).strip() or sender.username or "unknown"
            except Exception:
                pass
            messages.append({
                "sender": sender_name,
                "text": msg.text.strip(),
                "date": msg.date.replace(tzinfo=timezone.utc).isoformat(),
            })

    messages.sort(key=lambda m: m["date"])
    log.info("Fetched %d messages", len(messages))
    return messages
