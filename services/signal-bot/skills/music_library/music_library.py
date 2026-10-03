"""Read-only, narrowly scoped inspection of the mounted music library."""

from datetime import datetime, timezone
from pathlib import Path

from strands import tool

MUSIC_ROOT = Path("/music")
MAX_RESULTS = 10


def _describe(path: Path) -> str:
    stat = path.stat()
    relative = path.relative_to(MUSIC_ROOT)
    modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"/music/{relative} | {stat.st_size} bytes | modified {modified}"


@tool
def inspect_music_library(query: str = "") -> str:
    """Find MP3 files strictly inside /music and report verified file metadata.

    Use this only to verify music-library downloads, locations, sizes, or recent
    MP3 files. Never use PDF, image, or web tools to test whether an MP3 exists.

    Args:
        query: Filename/path fragment to find. Leave empty to list recent MP3s.
    """
    if not MUSIC_ROOT.is_dir():
        return "Music library is unavailable: /music is not mounted."

    needle = query.strip().lower().removeprefix("/music/")
    files = [p for p in MUSIC_ROOT.rglob("*.mp3") if p.is_file()]
    if needle:
        files = [p for p in files if needle in str(p.relative_to(MUSIC_ROOT)).lower()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    if not files:
        return f"No MP3 found in /music matching {query!r}." if needle else "No MP3 files found in /music."
    shown = files[:MAX_RESULTS]
    heading = f"Verified {len(files)} matching MP3 file(s) in /music:"
    return heading + "\n" + "\n".join(_describe(path) for path in shown)
