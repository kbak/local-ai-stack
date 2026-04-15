"""Persistent state for calendar-watcher."""

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
    event_type: str          # "meal" | "travel" | "ignored"
    briefing_sent: bool
    briefing_sent_at: str | None   # ISO 8601 UTC
    weather_sent: bool = False     # for travel: 24h-before weather notification
    weather_sent_at: str | None = None


@dataclass
class State:
    events: dict[str, EventRecord]
    last_anchor_city: str | None = None  # city of the last confirmed travel anchor

    def to_dict(self) -> dict:
        return {
            "events": {uid: asdict(r) for uid, r in self.events.items()},
            "last_anchor_city": self.last_anchor_city,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "State":
        return cls(
            events={uid: EventRecord(**v) for uid, v in d.get("events", {}).items()},
            last_anchor_city=d.get("last_anchor_city"),
        )


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
