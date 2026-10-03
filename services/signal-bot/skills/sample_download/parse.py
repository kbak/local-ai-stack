"""Parse `/sample` input into (url, start_seconds, length_seconds, name_hint)."""

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

_URL_RE = re.compile(r"https?://\S+")
# hh:mm:ss / mm:ss / ss — whole-token timestamp
_TS_RE = re.compile(r"^\d{1,2}(?::\d{1,2}){0,2}$")


@dataclass
class ParsedInput:
    url: str
    start_s: float
    length_s: float
    name_hint: str = ""


def parse_timestamp(s: str) -> Optional[float]:
    """Parse `hh:mm:ss`, `mm:ss`, or `ss` into seconds. Returns None if invalid."""
    if not _TS_RE.match(s):
        return None
    parts = [int(p) for p in s.split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def _start_from_url(url: str) -> float:
    """Extract `t=` / `start=` start time (in seconds) from a YouTube URL, else 0."""
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        # Also pick up `t=` / `start=` from the URL fragment (e.g. `#t=30`)
        if parsed.fragment:
            qs.update(parse_qs(parsed.fragment))
        for key in ("t", "start"):
            if key in qs and qs[key]:
                raw = qs[key][0]
                # Forms: "30", "30s", "1m30s", "1h2m3s"
                if raw.isdigit():
                    return float(raw)
                m = re.match(
                    r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$",
                    raw,
                )
                if m and any(m.groups()):
                    h = int(m.group(1) or 0)
                    mm = int(m.group(2) or 0)
                    ss = int(m.group(3) or 0)
                    return float(h * 3600 + mm * 60 + ss)
    except Exception:
        pass
    return 0.0


def parse(text: str) -> ParsedInput:
    """Parse user input; raises ValueError on invalid grammar.

    Grammar (whitespace-separated tokens):
        <url> [start_ts] <length_ts> [name_hint...]
    where:
        - start_ts and length_ts are timestamps (`hh:mm:ss` / `mm:ss` / `ss`)
        - if exactly one timestamp is present it is treated as length;
          start defaults to URL `?t=` / `start=` or 0
        - name_hint is any trailing token(s) after the timestamps
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("missing URL")

    url_match = _URL_RE.search(text)
    if not url_match:
        raise ValueError("missing URL")
    url = url_match.group(0)

    # Tokens after the URL (timestamps + optional hint)
    tail = text[url_match.end():].strip()
    tokens = tail.split() if tail else []

    timestamps: list[float] = []
    hint_tokens: list[str] = []
    for tok in tokens:
        if not timestamps or len(timestamps) < 2:
            ts = parse_timestamp(tok)
            if ts is not None:
                timestamps.append(ts)
                continue
        # Once we hit a non-timestamp, everything after is hint
        hint_tokens.append(tok)

    if not timestamps:
        raise ValueError("missing length")

    if len(timestamps) == 1:
        length_s = timestamps[0]
        start_s = _start_from_url(url)
    else:
        start_s, length_s = timestamps[0], timestamps[1]

    if length_s <= 0:
        raise ValueError("length must be > 0")

    return ParsedInput(
        url=url,
        start_s=start_s,
        length_s=length_s,
        name_hint=" ".join(hint_tokens).strip(),
    )
