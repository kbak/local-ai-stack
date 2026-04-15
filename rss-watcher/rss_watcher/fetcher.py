"""Fetch RSS feeds and return recent items grouped by category."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser

log = logging.getLogger(__name__)


def _parse_date(entry) -> datetime | None:
    for field in ("published", "updated"):
        raw = entry.get(f"{field}_parsed") or entry.get(field)
        if raw is None:
            continue
        if isinstance(raw, str):
            try:
                return parsedate_to_datetime(raw).astimezone(timezone.utc)
            except Exception:
                continue
        # struct_time from feedparser
        try:
            import calendar
            return datetime.fromtimestamp(calendar.timegm(raw), tz=timezone.utc)
        except Exception:
            continue
    return None


def fetch_category(urls: list[str], lookback_hours: int) -> list[dict]:
    """Return items from all urls published within lookback_hours, newest first."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    items: list[dict] = []

    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                pub = _parse_date(entry)
                if pub is None or pub < cutoff:
                    continue
                items.append({
                    "title": entry.get("title", "").strip(),
                    "link": entry.get("link", ""),
                    "summary": entry.get("summary", entry.get("description", "")).strip()[:300],
                    "published": pub.isoformat(),
                    "source": feed.feed.get("title", url),
                })
        except Exception:
            log.exception("Failed to fetch feed: %s", url)

    items.sort(key=lambda x: x["published"], reverse=True)
    return items
