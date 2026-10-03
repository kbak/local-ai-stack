"""Parse `/roast` input.

Grammar:
    [lang] <person1>, <person2>[, [turns] [topic...]]

Where:
    lang     — 2-letter ISO code (en, pl, de, ...). Optional; auto if absent.
    person1  — free-form name, words separated by spaces. Required.
    person2  — same. Required. Separated from person1 by a comma.
    turns    — integer (2..30). Optional; defaults to 6. If present, must be the
               first token after the second comma.
    topic    — free text. Optional; defaults to a generic "argue about something"
               prompt. Everything after the second comma (minus an optional leading
               turns digit) is the topic.

Examples:
    /roast hillary clinton, donald trump
    /roast hillary clinton, donald trump, better than you
    /roast hillary clinton, donald trump, 8 better than you
    /roast pl hillary clinton, donald trump, 10 lepsza niz ty
"""

from __future__ import annotations

from dataclasses import dataclass

# Languages Chatterbox supports — used to detect a leading lang token.
_SUPPORTED_LANGS = {
    "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi",
    "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv",
    "sw", "tr", "zh",
}

DEFAULT_TURNS = 6

MIN_TURNS = 2
MAX_TURNS = 30


@dataclass
class Parsed:
    language: str | None      # None => auto-detect later via lingua, or English fallback
    person1: str
    person2: str
    turns: int
    topic: str | None         # None => LLM-generated at runtime


def parse(text: str) -> Parsed:
    """Parse `text` into a Parsed; raise ValueError on invalid grammar."""
    s = (text or "").strip()
    if not s:
        raise ValueError("missing input")
    if "," not in s:
        raise ValueError(
            "missing comma between the two names. "
            "Use `/roast person one, person two`."
        )

    # Split into up to three comma-separated parts: person1, person2, topic_part.
    parts = [p.strip() for p in s.split(",", 2)]
    head, mid = parts[0], parts[1]
    topic_part = parts[2] if len(parts) == 3 else ""

    # 1. Optional language code as the first token of part 1.
    lhs_tokens = head.split()
    language: str | None = None
    if lhs_tokens and len(lhs_tokens[0]) == 2 and lhs_tokens[0].lower() in _SUPPORTED_LANGS:
        language = lhs_tokens[0].lower()
        lhs_tokens = lhs_tokens[1:]
    if not lhs_tokens:
        raise ValueError("missing first person before the comma")
    person1 = " ".join(lhs_tokens).strip()

    # 2. Person2 = all of part 2.
    person2 = mid.strip()
    if not person2:
        raise ValueError("missing second person after the comma")

    # 3. Topic part: optional leading turns digit, rest is topic.
    turns = DEFAULT_TURNS
    topic: str | None = None
    if topic_part:
        topic_tokens = topic_part.split()
        if topic_tokens and topic_tokens[0].isdigit():
            turns = int(topic_tokens[0])
            if turns < MIN_TURNS or turns > MAX_TURNS:
                raise ValueError(f"turns must be between {MIN_TURNS} and {MAX_TURNS}")
            topic_tokens = topic_tokens[1:]
        topic = " ".join(topic_tokens).strip() or None

    return Parsed(
        language=language,
        person1=person1,
        person2=person2,
        turns=turns,
        topic=topic,
    )
