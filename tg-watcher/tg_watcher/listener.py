"""Telethon user-account listener — passively reads the target group."""

from __future__ import annotations

import logging

from telethon import TelegramClient, events
from telethon.tl.types import User

from .config import TG_API_ID, TG_API_HASH, TG_GROUP, TG_PHONE, TG_SESSION_FILE
from .db import save_message

log = logging.getLogger(__name__)


async def _sender_name(event) -> str | None:
    try:
        sender = await event.get_sender()
        if isinstance(sender, User):
            parts = [sender.first_name or "", sender.last_name or ""]
            return " ".join(p for p in parts if p).strip() or sender.username
    except Exception:
        pass
    return None


async def run_listener() -> None:
    """Connect as the user account and stream messages indefinitely."""
    client = TelegramClient(TG_SESSION_FILE, TG_API_ID, TG_API_HASH)

    await client.start(phone=TG_PHONE)  # TG_PHONE only needed on first run
    log.info("Telethon connected as %s", await client.get_me())

    entity = await client.get_entity(TG_GROUP)
    log.info("Watching group: %s (id=%s)", getattr(entity, "title", TG_GROUP), entity.id)

    @client.on(events.NewMessage(chats=entity))
    async def handler(event):
        text = event.message.text or ""
        if not text.strip():
            return
        sender = await _sender_name(event)
        save_message(
            msg_id=event.message.id,
            sender=sender,
            text=text,
            date=event.message.date,
        )
        log.debug("Stored msg %d from %s", event.message.id, sender)

    log.info("Listening for messages...")
    await client.run_until_disconnected()
