"""EmailBackend protocol + normalized message types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class MessageRef:
    """Opaque handle a backend uses to find a message again.

    backend_id: backend's native id (Gmail message id, IMAP UID, etc.)
    extra: free-form backend-specific routing (e.g. IMAP folder name).
    """
    backend_id: str
    extra: dict = field(default_factory=dict)


@dataclass
class MessageHeaders:
    ref: MessageRef
    from_addr: str              # raw From: header
    to_addr: str                # raw To: header
    subject: str
    date: datetime              # UTC
    message_id: str             # RFC 2822 Message-ID, may be empty


@dataclass
class Attachment:
    filename: str
    mime_type: str
    content: bytes


@dataclass
class Message:
    ref: MessageRef
    headers: MessageHeaders
    body_text: str              # best-effort plain text (HTML stripped if only HTML present)
    body_html: str              # empty if none
    attachments: list[Attachment]


class EmailBackend(Protocol):
    def list_inbox(self, since: datetime, unread_only: bool = True) -> list[MessageHeaders]:
        """Return message headers for inbox messages since `since` (UTC)."""
        ...

    def fetch_full(self, ref: MessageRef) -> Message:
        """Fetch full body + attachments for a specific message."""
        ...

    def archive(self, ref: MessageRef) -> None:
        """Move the message out of the inbox into the configured archive location."""
        ...
