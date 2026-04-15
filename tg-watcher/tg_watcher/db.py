"""SQLite store for incoming Telegram messages."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY,
            msg_id    INTEGER NOT NULL,
            sender    TEXT,
            text      TEXT,
            date      TEXT NOT NULL
        )
    """)
    con.commit()
    return con


def save_message(msg_id: int, sender: str | None, text: str, date: datetime) -> None:
    con = _conn()
    con.execute(
        "INSERT OR IGNORE INTO messages (msg_id, sender, text, date) VALUES (?, ?, ?, ?)",
        (msg_id, sender or "unknown", text, date.astimezone(timezone.utc).isoformat()),
    )
    con.commit()
    con.close()


def fetch_since(since: datetime) -> list[dict]:
    con = _conn()
    rows = con.execute(
        "SELECT sender, text, date FROM messages WHERE date >= ? ORDER BY date ASC",
        (since.astimezone(timezone.utc).isoformat(),),
    ).fetchall()
    con.close()
    return [{"sender": r[0], "text": r[1], "date": r[2]} for r in rows]


def prune_older_than(cutoff: datetime) -> None:
    """Remove messages older than cutoff to keep DB small."""
    con = _conn()
    con.execute(
        "DELETE FROM messages WHERE date < ?",
        (cutoff.astimezone(timezone.utc).isoformat(),),
    )
    con.commit()
    con.close()
