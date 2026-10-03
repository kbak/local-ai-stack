"""Greedy fuzzy match of a voice-hint prefix against the voice-samples directory."""

import re
import unicodedata
from typing import Optional


def _normalize(s: str) -> str:
    """Lowercase + strip diacritics + non-alphanumerics → spaces collapsed.

    Used so 'John Doe' and 'john_doe.wav' compare equal.
    """
    nfkd = unicodedata.normalize("NFKD", s)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9]+", " ", no_accents.lower())
    return cleaned.strip()


def _voice_signature(stem: str) -> str:
    """Canonical comparable form of a voice filename stem."""
    return _normalize(stem)


def match_voice(tokens: list[str], available: list[str]) -> tuple[Optional[str], list[str]]:
    """Greedy longest-prefix fuzzy match.

    Tries the first 1..len(tokens) tokens (joined with space) against the
    normalized form of each available voice stem. Returns the longest k for
    which a match exists.

    Special case: if a token is `<name>.wav`, that's treated as an explicit
    single-token match — use it verbatim with the .wav stripped, regardless
    of greediness.

    Returns (matched_voice_stem | None, remaining_tokens).
    """
    if not tokens:
        return None, []

    # Explicit `.wav` form — first token only, unambiguous override.
    first = tokens[0]
    if first.lower().endswith(".wav"):
        stem = first[:-4]
        # Honour the user's literal choice even if the file isn't there yet —
        # let the audio-api 404 carry the error message.
        return stem, tokens[1:]

    norm_available = {_voice_signature(v): v for v in available}
    if not norm_available:
        return None, tokens

    # Greedy: try the longest prefix first, fall back to shorter.
    max_k = min(len(tokens), 6)  # cap — voice names won't be longer than 6 tokens
    for k in range(max_k, 0, -1):
        candidate = " ".join(tokens[:k])
        sig = _voice_signature(candidate)
        if not sig:
            continue
        # Exact normalized hit
        if sig in norm_available:
            return norm_available[sig], tokens[k:]
        # Substring match — voice stem contains the candidate as a whole
        # word. So "barack" hits "barack_obama"; "biden" hits "joe_biden";
        # but a partial token like "obam" does NOT match (must be a full
        # token in the normalized stem to avoid false positives on short
        # inputs that happen to be substrings of unrelated names).
        sig_words = set(sig.split())
        substring_hits = [
            v for s, v in norm_available.items()
            if sig_words.issubset(set(s.split()))
        ]
        if len(substring_hits) == 1:
            return substring_hits[0], tokens[k:]

    return None, tokens
