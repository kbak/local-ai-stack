from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from . import state
from .calendar import create_events
from .config import AUDIT_FILE, INITIAL_LOOKBACK_HOURS
from .extract import extract
from .mail import archive, list_messages

log = logging.getLogger(__name__)


def _audit(**values) -> None:
    os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
    with open(AUDIT_FILE, "a") as file:
        file.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), **values}) + "\n")


def poll_once() -> None:
    current = state.load()
    since = datetime.fromisoformat(current.last_seen) if current.last_seen else datetime.now(timezone.utc) - timedelta(hours=INITIAL_LOOKBACK_HOURS)
    latest = since
    for message in list_messages(since):
        key = message.message_id or f"imap:{message.uid}"
        latest = max(latest, message.date)
        if key in current.processed:
            continue
        try:
            itinerary = extract(message)
            if not itinerary.is_travel or itinerary.confidence != "high" or not (itinerary.transports or itinerary.hotels):
                _audit(action="ignored", key=key, subject=message.subject, confidence=itinerary.confidence)
                current.processed.append(key)
                continue
            created = create_events(itinerary)
            archive(message.uid)
            current.processed.append(key)
            _audit(action="created", key=key, subject=message.subject, events=created)
        except Exception as error:
            log.exception("Failed to process %r; leaving it in inbox", message.subject)
            _audit(action="failed", key=key, subject=message.subject, error=type(error).__name__)
    current.last_seen = latest.isoformat()
    state.save(current)
