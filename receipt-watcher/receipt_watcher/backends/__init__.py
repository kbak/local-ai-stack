"""Backend construction. IMAP-only for now."""

from __future__ import annotations

from ..config import Account
from .base import EmailBackend
from .imap import ImapBackend


def load_backend(account: Account) -> EmailBackend:
    return ImapBackend(account)
