"""Classify a song into one of the user-configured music directories."""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MusicDir:
    subdir: str       # e.g. "electronic/edm"
    genre_tag: str    # ID3 genre, e.g. "EDM"


def load_music_dirs() -> list[MusicDir]:
    """Parse MUSIC_DIRS env var into a list of MusicDir entries.

    Format: "subdir1:GenreTag1,subdir2:GenreTag2,..."
    Example: "brasileira:Brasileira,electronic/edm:EDM,top40:Top 40"
    """
    raw = os.getenv("MUSIC_DIRS", "")
    if not raw:
        return [MusicDir("top40", "Top 40")]

    dirs = []
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" in entry:
            subdir, tag = entry.split(":", 1)
            dirs.append(MusicDir(subdir.strip(), tag.strip()))
        elif entry:
            # No genre tag specified — use the last path component capitalized
            tag = entry.split("/")[-1].capitalize()
            dirs.append(MusicDir(entry.strip(), tag))

    return dirs


def classify(artist: str, title: str, genre_hint: str, user_hint: str = "") -> MusicDir:
    """Classify a song, returning the target MusicDir.

    Priority:
    1. user_hint (inline message like "brasileira") — matched against subdir names/genre tags
    2. LLM classification using MUSIC_CLASSIFY_PROMPT
    3. Fallback: last directory in the list (expected to be top40/catch-all)
    """
    dirs = load_music_dirs()

    # 1. User inline hint — fuzzy match against subdir path or genre tag
    if user_hint:
        hint_lower = user_hint.lower().strip()
        for d in dirs:
            if hint_lower in d.subdir.lower() or hint_lower in d.genre_tag.lower():
                logger.info("User hint '%s' matched dir: %s", user_hint, d.subdir)
                return d
        logger.warning("User hint '%s' didn't match any dir, falling back to LLM", user_hint)

    # 2. LLM classification
    classify_prompt = os.getenv(
        "MUSIC_CLASSIFY_PROMPT",
        "Polish rock or disco polo -> polska; "
        "sertanejo or traditional Brazilian music -> brasileira; "
        "other Latin music (excluding Brazilian) -> latino; "
        "house music -> electronic/house; "
        "long DJ sets or electronic music -> electronic/edm; "
        "rock -> rock; "
        "everything else -> top40",
    )

    dir_names = ", ".join(d.subdir for d in dirs)

    prompt = (
        f"Classify the following song into exactly one of these directories: {dir_names}\n\n"
        f"Classification rules:\n{classify_prompt}\n\n"
        f"Song: {artist} - {title}\n"
        f"Genre hints from metadata: {genre_hint or 'none'}\n\n"
        f"Reply with ONLY the directory name, nothing else. "
        f"Pick the single best match."
    )

    try:
        import config
        from openai import OpenAI

        client = OpenAI(base_url=config.llm.base_url, api_key=config.llm.api_key)
        resp = client.chat.completions.create(
            model=config.llm.model_id,
            messages=[
                {"role": "system", "content": "You are a music genre classifier. Reply with only the directory name, nothing else."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=16,
            temperature=0,
        )
        result = resp.choices[0].message.content.strip().lower()
        logger.info("LLM classified '%s - %s' as: %s", artist, title, result)

        for d in dirs:
            if d.subdir.lower() == result or d.genre_tag.lower() == result:
                return d
            # partial match (e.g. LLM said "edm" and subdir is "electronic/edm")
            if result in d.subdir.lower() or d.subdir.lower() in result:
                return d

        logger.warning("LLM returned unrecognized dir '%s', using fallback", result)
    except Exception as e:
        logger.error("LLM classification failed: %s", e)

    # 3. Fallback: last dir (assumed to be top40 or catch-all)
    return dirs[-1]
