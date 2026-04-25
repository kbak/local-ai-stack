"""Resolve a `firstname_lastname` filename stem from a YouTube title (LLM + transliteration)."""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

_NON_ASCII_RE = re.compile(r"[^a-z0-9_]+")
_FALLBACK_MAX_LEN = 24
_MAX_NAME_PARTS = 3


# Latin letters NFKD doesn't decompose (stroke/yogh/ash/eth/etc.)
_TRANSLIT = str.maketrans({
    "ł": "l", "Ł": "L",
    "ø": "o", "Ø": "O",
    "æ": "ae", "Æ": "Ae",
    "œ": "oe", "Œ": "Oe",
    "ß": "ss",
    "ð": "d", "Ð": "D",
    "þ": "th", "Þ": "Th",
})


def _normalise(raw: str) -> str:
    """Lowercase + strip diacritics + replace non-[a-z0-9_] with single underscores."""
    transliterated = raw.translate(_TRANSLIT)
    nfkd = unicodedata.normalize("NFKD", transliterated)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    lowered = no_accents.lower().replace(" ", "_")
    cleaned = _NON_ASCII_RE.sub("_", lowered).strip("_")
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned


def _trim_name_parts(name: str) -> str:
    """Limit a normalised name to at most _MAX_NAME_PARTS underscore-separated parts."""
    parts = [p for p in name.split("_") if p]
    return "_".join(parts[:_MAX_NAME_PARTS])


def _slug_fallback(title: str) -> str:
    """Build a slug from the YouTube title when no speaker name can be derived."""
    n = _normalise(title)
    return n[:_FALLBACK_MAX_LEN].rstrip("_") or "sample"


def from_hint(hint: str) -> str:
    """Convert a user-provided hint into a safe filename stem."""
    n = _normalise(hint)
    return _trim_name_parts(n) or "sample"


def from_title(title: str, artist: str = "") -> str:
    """Ask the LLM to extract a speaker's `firstname_lastname` from a YouTube title.

    Falls back to a slug of the title when the LLM is unavailable or returns
    something unusable.
    """
    try:
        # Sibling-package import (added to sys.path by sample.py before import)
        from _shared.llm import chat
    except ImportError:  # pragma: no cover
        return _slug_fallback(title)

    system = (
        "You extract a speaker's name from a YouTube video title for use as a "
        "voice-clone sample filename. Reply with ONLY the name, lowercase, "
        "ASCII-only, words separated by single underscores (e.g. "
        "`barack_obama`, `madonna`, `martin_luther_king`). At most three "
        "name parts. Drop suffixes like Jr/Sr/III. If the video is not a "
        "person speaking (e.g. a music track without a clear primary speaker), "
        "reply with the single word: NONE."
    )
    user = f"Title: {title}"
    if artist:
        user += f"\nUploader/Artist: {artist}"

    raw = chat(system, user, max_tokens=64, temperature=0.0)
    if not raw:
        return _slug_fallback(title)

    cleaned = raw.strip().strip("`'\".,;:!?").splitlines()[0].strip()
    if cleaned.upper() == "NONE" or not cleaned:
        return _slug_fallback(title)

    normalised = _normalise(cleaned)
    trimmed = _trim_name_parts(normalised)
    if not trimmed:
        return _slug_fallback(title)
    return trimmed
