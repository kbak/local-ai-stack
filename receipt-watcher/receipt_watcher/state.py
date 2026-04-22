"""Persistent state: per-account last_seen timestamp + processed message-id set."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import STATE_FILE

log = logging.getLogger(__name__)


@dataclass
class AccountState:
    # ISO-8601 UTC timestamp of the most recent message we've looked at.
    last_seen: str | None = None
    # Set of backend-native message IDs we've already processed, to guard against
    # clock-skew or re-delivery. Capped in size by save() to avoid unbounded growth.
    processed_ids: list[str] = field(default_factory=list)

    def mark_processed(self, message_id: str) -> None:
        if message_id and message_id not in self.processed_ids:
            self.processed_ids.append(message_id)

    def has_processed(self, message_id: str) -> bool:
        return bool(message_id) and message_id in self.processed_ids


@dataclass
class State:
    accounts: dict[str, AccountState] = field(default_factory=dict)

    def for_account(self, name: str) -> AccountState:
        if name not in self.accounts:
            self.accounts[name] = AccountState()
        return self.accounts[name]

    def to_dict(self) -> dict:
        return {
            "accounts": {
                name: {
                    "last_seen": s.last_seen,
                    "processed_ids": s.processed_ids[-2000:],   # cap
                }
                for name, s in self.accounts.items()
            }
        }

    @classmethod
    def from_dict(cls, d: dict) -> "State":
        out = cls()
        for name, raw in (d.get("accounts", {}) or {}).items():
            out.accounts[name] = AccountState(
                last_seen=raw.get("last_seen"),
                processed_ids=list(raw.get("processed_ids", [])),
            )
        return out


def load() -> State:
    if not os.path.exists(STATE_FILE):
        return State()
    try:
        with open(STATE_FILE) as f:
            return State.from_dict(json.load(f))
    except Exception:
        log.exception("Failed to load state, starting fresh")
        return State()


def save(state: State) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state.to_dict(), f, indent=2)
    os.replace(tmp, STATE_FILE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
