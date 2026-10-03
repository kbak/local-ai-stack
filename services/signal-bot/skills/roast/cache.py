"""On-disk persona cache.

Personas are deterministic given a name and don't change often, but generating
them takes a 5-15s LLM round-trip with tool calls. Cache them in the bot's
data volume so repeat /roast invocations are instant for known speakers.
"""

import logging
import re
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path("/app/data/persona_cache")


def _slug(name: str) -> str:
    """Normalize a name to a safe filename stem.

    Same shape as a voice-file stem: lowercase ASCII, underscores, no diacritics.
    `Donald J. Trump` → `donald_j_trump`. Used as the persona-cache key so the
    same person resolves the same file regardless of casing/punctuation.
    """
    nfkd = unicodedata.normalize("NFKD", name)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9]+", "_", no_accents.lower()).strip("_")
    return re.sub(r"_+", "_", cleaned) or "unknown"


def _path_for(name: str) -> Path:
    return CACHE_DIR / f"{_slug(name)}.txt"


def get(name: str) -> str | None:
    """Return cached persona text for `name`, or None if not cached."""
    p = _path_for(name)
    if p.exists():
        try:
            return p.read_text(encoding="utf-8").strip() or None
        except Exception as e:
            logger.warning("persona cache read failed for %s: %s", name, e)
    return None


def put(name: str, persona: str) -> None:
    """Persist `persona` for `name`. Failures log a warning and continue."""
    if not persona or not persona.strip():
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _path_for(name).write_text(persona.strip(), encoding="utf-8")
        logger.info("cached persona for '%s' (%d chars)", name, len(persona))
    except Exception as e:
        logger.warning("persona cache write failed for %s: %s", name, e)
