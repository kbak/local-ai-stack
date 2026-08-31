from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from imap_tools import AND, MailBox

from .config import IMAP_HOST, IMAP_PASSWORD, IMAP_PORT, IMAP_USERNAME

log = logging.getLogger(__name__)


@dataclass
class Attachment:
    filename: str
    mime_type: str
    content: bytes


@dataclass
class Message:
    uid: str
    message_id: str
    sender: str
    subject: str
    date: datetime
    text: str
    html: str
    attachments: list[Attachment]


def _open() -> MailBox:
    return MailBox(IMAP_HOST, IMAP_PORT).login(IMAP_USERNAME, IMAP_PASSWORD, initial_folder="INBOX")


def list_messages(since: datetime) -> list[Message]:
    result: list[Message] = []
    with _open() as box:
        for msg in box.fetch(AND(date_gte=since.date(), seen=False), mark_seen=False, bulk=False):
            dt = msg.date or datetime.now(timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            result.append(Message(
                uid=str(msg.uid), message_id=(msg.headers.get("message-id", ("",)) or ("",))[0],
                sender=msg.from_ or "", subject=msg.subject or "", date=dt.astimezone(timezone.utc),
                text=msg.text or "", html=msg.html or "",
                attachments=[Attachment(a.filename or "", a.content_type or "application/octet-stream", a.payload or b"") for a in msg.attachments],
            ))
    return result


def archive(uid: str) -> None:
    with _open() as box:
        if IMAP_HOST.lower() in ("imap.gmail.com", "imap.googlemail.com"):
            status, _ = box.client.uid("STORE", uid, "-X-GM-LABELS", "(\\Inbox)")
            if status != "OK":
                raise RuntimeError(f"Gmail archive failed: {status}")
            return
        for folder in box.folder.list():
            delimiter = folder.delim or "/"
            if folder.name.rsplit(delimiter, 1)[-1].lower() == "archive":
                box.move([uid], folder.name)
                return
        raise RuntimeError("No Archive folder found")
