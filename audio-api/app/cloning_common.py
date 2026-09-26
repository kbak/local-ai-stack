"""Voice sample lookup and text boundaries shared by cloning backends."""

from pathlib import Path
import re

from . import config


def list_voices() -> list[str]:
    return sorted(p.stem for p in config.VOICE_SAMPLES_DIR.glob("*.wav"))


def resolve_voice(voice: str | None) -> str | None:
    if not voice:
        return None
    path = Path(voice)
    if not (path.is_absolute() and path.suffix == ".wav"):
        path = config.VOICE_SAMPLES_DIR / f"{voice}.wav"
    if not path.is_file():
        raise FileNotFoundError(f"voice not found: {path}")
    return str(path)


def split_for_generation(text: str, max_chars: int = 350) -> list[str]:
    """Bound sentence groups without reordering or dropping text."""
    pieces = []
    current = ""
    for sentence in re.split(r"(?<=[.!?…])\s+", text):
        if not sentence:
            continue
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut])
            sentence = sentence[cut:].lstrip()
        if len(current) + len(sentence) + 1 > max_chars and current:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces
