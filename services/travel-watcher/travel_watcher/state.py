from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .config import STATE_FILE


@dataclass
class State:
    last_seen: str | None = None
    processed: list[str] = field(default_factory=list)


def load() -> State:
    try:
        with open(STATE_FILE) as file:
            raw = json.load(file)
        return State(raw.get("last_seen"), list(raw.get("processed", [])))
    except (FileNotFoundError, ValueError, TypeError):
        return State()


def save(state: State) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as file:
        json.dump({"last_seen": state.last_seen, "processed": state.processed[-5000:]}, file)
    os.replace(tmp, STATE_FILE)
