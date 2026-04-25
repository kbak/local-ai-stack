"""Parse `/roast` input.

Grammar:
    [lang] <person1>, <person2> [turns] [topic...]

Where:
    lang     — 2-letter ISO code (en, pl, de, ...). Optional; auto if absent.
    person1  — free-form name, words separated by spaces. Required.
    person2  — same. Required. Separated from person1 by a comma.
    turns    — integer (2..30). Optional; defaults to 6.
    topic    — free text. Optional; defaults to a generic "argue about something" prompt.

Examples:
    /roast hillary clinton, donald trump
    /roast hillary clinton, donald trump 8 better than you
    /roast pl hillary clinton, donald trump 10 lepszy niz ty
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

    # 1. Optional language code as the first token.
    head, _, rest = s.partition(",")
    lhs_tokens = head.strip().split()
    language: str | None = None
    if lhs_tokens and len(lhs_tokens[0]) == 2 and lhs_tokens[0].lower() in _SUPPORTED_LANGS:
        language = lhs_tokens[0].lower()
        lhs_tokens = lhs_tokens[1:]
    if not lhs_tokens:
        raise ValueError("missing first person before the comma")
    person1 = " ".join(lhs_tokens).strip()

    # 2. RHS: <person2 tokens...> [turns] [topic...]
    rhs_tokens = rest.strip().split()
    if not rhs_tokens:
        raise ValueError("missing second person after the comma")

    # Consume person2 tokens until we either (a) hit a numeric token (turns)
    # or (b) reach the end. Person2 is the run of leading non-numeric tokens.
    p2_tokens: list[str] = []
    i = 0
    while i < len(rhs_tokens) and not rhs_tokens[i].isdigit():
        p2_tokens.append(rhs_tokens[i])
        i += 1
    if not p2_tokens:
        raise ValueError("second person name cannot start with a number")
    person2 = " ".join(p2_tokens).strip()

    # 3. Optional turns (a single integer token).
    turns = DEFAULT_TURNS
    if i < len(rhs_tokens) and rhs_tokens[i].isdigit():
        turns = int(rhs_tokens[i])
        i += 1
        if turns < MIN_TURNS or turns > MAX_TURNS:
            raise ValueError(f"turns must be between {MIN_TURNS} and {MAX_TURNS}")

    # 4. Remaining tokens = topic. Empty -> None so the caller LLM-generates one.
    topic = " ".join(rhs_tokens[i:]).strip() or None

    return Parsed(
        language=language,
        person1=person1,
        person2=person2,
        turns=turns,
        topic=topic,
    )
