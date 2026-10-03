"""Filename helpers shared across skills."""

import re
from pathlib import Path

_FS_UNSAFE_RE = re.compile(r'[<>:"/\\|?*]')


def safe_component(s: str) -> str:
    """Strip filesystem-unsafe characters from a single path component."""
    return _FS_UNSAFE_RE.sub("", s).strip()


def artist_title_filename(artist: str, title: str) -> str:
    """Build a 'Artist - Title' string safe for the filesystem (no extension)."""
    return f"{safe_component(artist)} - {safe_component(title)}"


def unique_path(directory: Path, base_name: str, ext: str) -> Path:
    """Return a path under `directory` that doesn't exist yet, suffixing (2), (3)... as needed.

    `ext` should include the leading dot, e.g. ".wav".
    """
    candidate = directory / f"{base_name}{ext}"
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = directory / f"{base_name} ({counter}){ext}"
        if not candidate.exists():
            return candidate
        counter += 1
