"""Persistent state.

Two layers:
- anchors: uid → RawAnchor  (incremental parsing, change detection)
- spans:   list[LocationSpan]  (derived, chronological, what get_location_at queries)

Spans are recomputed from anchors after every poll and stored alongside them.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass

from .config import STATE_FILE

log = logging.getLogger(__name__)


@dataclass
class RawAnchor:
    """One travel event as parsed — uid-keyed, used for incremental updates."""
    uid: str
    city: str | None        # None = not a travel event
    confidence: str | None
    source: str
    start_utc: str          # ISO 8601 UTC
    end_utc: str            # ISO 8601 UTC
    content_hash: str


@dataclass
class LocationSpan:
    """A continuous period during which the user is in a given city."""
    from_utc: str           # ISO 8601 UTC — start of this city period
    to_utc: str | None      # ISO 8601 UTC — end, or None meaning "open-ended"
    city: str
    confidence: str
    source: str


@dataclass
class State:
    anchors: dict[str, RawAnchor]   # uid → anchor
    spans: list[LocationSpan]       # derived, sorted by from_utc

    def to_dict(self) -> dict:
        return {
            "anchors": {uid: asdict(a) for uid, a in self.anchors.items()},
            "spans": [asdict(s) for s in self.spans],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "State":
        anchors = {
            uid: RawAnchor(**v)
            for uid, v in d.get("anchors", {}).items()
        }
        spans = [LocationSpan(**s) for s in d.get("spans", [])]
        return cls(anchors=anchors, spans=spans)


def load() -> State:
    if not os.path.exists(STATE_FILE):
        return State(anchors={}, spans=[])
    try:
        with open(STATE_FILE) as f:
            return State.from_dict(json.load(f))
    except Exception:
        log.exception("Failed to load state, starting fresh")
        return State(anchors={}, spans=[])


def save(state: State) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state.to_dict(), f, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception:
        log.exception("Failed to save state")
