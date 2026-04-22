"""Generic IMAP backend using imap-tools."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from imap_tools import AND, MailBox

from ..config import Account
from .base import Attachment, EmailBackend, Message, MessageHeaders, MessageRef

log = logging.getLogger(__name__)


class ImapBackend(EmailBackend):
    def __init__(self, account: Account) -> None:
        self.account = account
        self._host: str = account.auth["host"]
        self._port: int = int(account.auth.get("port", 993))
        self._username: str = account.auth["username"]
        pw_env = account.auth["password_env"]
        self._password: str = os.environ.get(pw_env, "")
        if not self._password:
            log.warning("IMAP password env var %s is empty for account %s", pw_env, account.name)

    def _open(self) -> MailBox:
        mb = MailBox(self._host, self._port)
        mb.login(self._username, self._password, initial_folder="INBOX")
        return mb

    def list_inbox(self, since: datetime, unread_only: bool = True) -> list[MessageHeaders]:
        since_date = since.astimezone(timezone.utc).date()
        criteria = AND(date_gte=since_date, seen=False) if unread_only else AND(date_gte=since_date)

        out: list[MessageHeaders] = []
        with self._open() as mb:
            for msg in mb.fetch(criteria, mark_seen=False, bulk=False, headers_only=True):
                dt = msg.date
                if dt is None:
                    dt = datetime.now(timezone.utc)
                elif dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                out.append(
                    MessageHeaders(
                        ref=MessageRef(backend_id=str(msg.uid), extra={"folder": "INBOX"}),
                        from_addr=msg.from_ or "",
                        to_addr=", ".join(msg.to or ()),
                        subject=msg.subject or "",
                        date=dt.astimezone(timezone.utc),
                        message_id=(msg.headers.get("message-id", ("",)) or ("",))[0],
                    )
                )
        return out

    def fetch_full(self, ref: MessageRef) -> Message:
        with self._open() as mb:
            folder = ref.extra.get("folder", "INBOX")
            if folder != "INBOX":
                mb.folder.set(folder)
            msgs = list(mb.fetch(AND(uid=ref.backend_id), mark_seen=False, bulk=False))
            if not msgs:
                raise RuntimeError(f"IMAP message uid={ref.backend_id} not found in {folder}")
            msg = msgs[0]

            dt = msg.date or datetime.now(timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            headers = MessageHeaders(
                ref=ref,
                from_addr=msg.from_ or "",
                to_addr=", ".join(msg.to or ()),
                subject=msg.subject or "",
                date=dt.astimezone(timezone.utc),
                message_id=(msg.headers.get("message-id", ("",)) or ("",))[0],
            )
            atts = [
                Attachment(
                    filename=a.filename or "",
                    mime_type=a.content_type or "application/octet-stream",
                    content=a.payload or b"",
                )
                for a in msg.attachments
            ]
            return Message(
                ref=ref,
                headers=headers,
                body_text=msg.text or "",
                body_html=msg.html or "",
                attachments=atts,
            )

    def archive(self, ref: MessageRef) -> None:
        raise NotImplementedError("archival not wired in scaffold phase")
