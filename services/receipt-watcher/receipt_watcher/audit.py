"""JSONL audit log — one line per processed email."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from .config import AUDIT_LOG_FILE

log = logging.getLogger(__name__)


def append(entry: dict) -> None:
    entry = {"ts": datetime.now(timezone.utc).isoformat(), **entry}
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG_FILE), exist_ok=True)
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        log.exception("Failed to append audit entry")
