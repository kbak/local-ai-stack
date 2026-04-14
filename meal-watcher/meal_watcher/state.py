"""Persistent state for meal-watcher.

Tracks which events have been processed and whether reminders have been scheduled/sent.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass

from .config import STATE_FILE

log = logging.getLogger(__name__)


@dataclass
class EventRecord:
    uid: str
    content_hash: str
    briefing_sent: bool
    briefing_sent_at: str | None  # ISO 8601 UTC
    is_meal: bool = False  # True if classified as meal event


@dataclass
class State:
    events: dict[str, EventRecord]  # uid → record

    def to_dict(self) -> dict:
        return {"events": {uid: asdict(r) for uid, r in self.events.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> "State":
        return cls(events={
            uid: EventRecord(**v)
            for uid, v in d.get("events", {}).items()
        })


def load() -> State:
    if not os.path.exists(STATE_FILE):
        return State(events={})
    try:
        with open(STATE_FILE) as f:
            return State.from_dict(json.load(f))
    except Exception:
        log.exception("Failed to load state, starting fresh")
        return State(events={})


def save(state: State) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state.to_dict(), f, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception:
        log.exception("Failed to save state")
