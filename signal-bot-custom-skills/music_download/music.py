"""Music download skill — the main @tool entry point."""

import logging
import os
import re
import sys
import tempfile
from pathlib import Path

from strands import tool

# Ensure sibling modules (metadata, classify, trim) are importable
_SKILL_DIR = str(Path(__file__).parent)
if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)
# Ensure sibling-skill `_shared/` package is importable
_CUSTOM_SKILLS_ROOT = str(Path(__file__).parent.parent)
if _CUSTOM_SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _CUSTOM_SKILLS_ROOT)

from _shared.files import artist_title_filename, unique_path  # noqa: E402
from _shared.ytdlp import download_audio  # noqa: E402

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+")
# Matches a leading word/phrase that looks like a genre hint (no slashes or dots, before a URL)
_HINT_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9 _-]{0,30}?)\s+https?://", re.IGNORECASE)


def _parse_input(text: str) -> tuple[str, str]:
    """Split 'input' into (user_hint, url). Either may be empty."""
    text = text.strip()
    m = _HINT_RE.match(text)
    if m:
        hint = m.group(1).strip()
        url_match = _URL_RE.search(text)
        url = url_match.group(0) if url_match else ""
        return hint, url

    url_match = _URL_RE.search(text)
    if url_match:
        return "", url_match.group(0)

    return "", text


def _set_tags(path: str, artist: str, title: str, album: str, year: str, genre: str, cover_url: str):
    """Write ID3 tags to the mp3 using mutagen."""
    try:
        from mutagen.id3 import (
            ID3, TIT2, TPE1, TALB, TDRC, TCON, APIC, ID3NoHeaderError,
        )
        import httpx

        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()

        tags["TIT2"] = TIT2(encoding=3, text=title)
        tags["TPE1"] = TPE1(encoding=3, text=artist)
        if album:
            tags["TALB"] = TALB(encoding=3, text=album)
        if year:
            tags["TDRC"] = TDRC(encoding=3, text=year)
        if genre:
            tags["TCON"] = TCON(encoding=3, text=genre)

        if cover_url:
            try:
                resp = httpx.get(cover_url, timeout=10)
                resp.raise_for_status()
                tags["APIC:"] = APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,  # cover front
                    desc="Cover",
                    data=resp.content,
                )
            except Exception as e:
                logger.warning("Cover art fetch failed: %s", e)

        tags.save(path, v2_version=3)
        logger.info("ID3 tags written to %s", path)
    except ImportError:
        logger.warning("mutagen not installed — skipping ID3 tags")
    except Exception as e:
        logger.error("Tag writing failed: %s", e)


@tool
def download_music(input: str, images: list | None = None, status_fn=None) -> str:
    """Download a song as MP3 from a Shazam or Spotify link (or a screenshot of either app).

    Finds the song on YouTube, downloads the highest quality audio, trims non-music
    content from start and end, classifies it into the right directory, and sets
    ID3 metadata including cover art.

    Usage patterns:
    - /music https://shazam.com/track/...
    - /music https://open.spotify.com/track/...
    - /music brasileira https://shazam.com/track/...   (inline genre hint)
    - Send a screenshot of Shazam/Spotify together with /music or just the text

    Args:
        input: A Shazam/Spotify URL, optionally preceded by a genre directory hint.
               May also be an artist/title string if URL parsing failed upstream.
        images: Optional list of OpenAI-format image content blocks (from bot image handling).
    """
    from metadata import resolve_from_text, resolve_from_image
    from classify import classify, load_music_dirs
    from trim import trim_audio

    def status(msg: str):
        logger.info(msg)
        if status_fn:
            status_fn(msg)

    base_dir = "/music"

    # --- Parse input ---
    user_hint, url = _parse_input(input)
    logger.info("Music request: hint=%r url=%r images=%d", user_hint, url, len(images or []))

    # --- Resolve metadata ---
    meta = None
    if url:
        meta = resolve_from_text(url)

    # Try image-based extraction if we have attached images and no structured meta yet
    if meta is None and images:
        for img_block in images:
            img_data = img_block.get("image_url", {}).get("url", "")
            if img_data.startswith("data:"):
                # data:<content_type>;base64,<data>
                header, b64 = img_data.split(",", 1)
                content_type = header.split(":")[1].split(";")[0]
                meta = resolve_from_image(b64, content_type)
                if meta:
                    break

    if meta is None:
        if not url and not images:
            return (
                "Please send a Shazam or Spotify link. "
                "You can also send a screenshot of either app with the /music command."
            )
        if not url:
            return "Could not extract song info from the image. Please also include a Shazam or Spotify link."
        # Use yt-dlp's own metadata as fallback — search by URL directly
        logger.info("No structured metadata, will use yt-dlp metadata from URL")

    song_label = f"{meta.artist} - {meta.title}" if meta else url
    status(f"Searching YouTube for: {song_label}")

    with tempfile.TemporaryDirectory() as tmp:
        # --- Download from YouTube ---
        search_target = (meta.search_query if meta else url)

        raw_mp3 = os.path.join(tmp, "download.mp3")
        try:
            yt_artist, yt_title = download_audio(search_target, raw_mp3, timeout=120)
        except Exception as e:
            logger.exception("Download failed")
            return f"Download failed: {e}"

        # If we have no structured meta, use what yt-dlp returned
        if meta is None:
            from metadata import SongMeta
            artist = yt_artist or "Unknown"
            title_tag = yt_title or Path(raw_mp3).stem
            meta = SongMeta(artist=artist, title=title_tag)
            meta.search_query = f"{artist} {title_tag} official audio"

        status(f"Downloaded: {meta.artist} - {meta.title}. Trimming...")

        # --- Trim ---
        trimmed_mp3 = os.path.join(tmp, "trimmed.mp3")
        try:
            trim_start, trim_end = trim_audio(raw_mp3, trimmed_mp3)
        except Exception as e:
            logger.warning("Trim failed (%s), using untrimmed file", e)
            import shutil
            shutil.copy2(raw_mp3, trimmed_mp3)
            trim_start, trim_end = 0.0, 0.0

        status("Classifying...")

        # --- Classify ---
        music_dir = classify(meta.artist, meta.title, meta.genre_hint, user_hint)
        target_dir = Path(base_dir) / music_dir.subdir
        target_dir.mkdir(parents=True, exist_ok=True)

        # --- Final filename & copy ---
        base_name = artist_title_filename(meta.artist, meta.title)
        final_path = unique_path(target_dir, base_name, ".mp3")

        import shutil
        shutil.copy2(trimmed_mp3, final_path)

        # --- ID3 tags ---
        _set_tags(
            str(final_path),
            artist=meta.artist,
            title=meta.title,
            album=meta.album,
            year=meta.year,
            genre=music_dir.genre_tag,
            cover_url=meta.cover_url,
        )

    trim_info = ""
    if trim_start > 0.1 or trim_end > 0.1:
        trim_info = f" (trimmed {trim_start:.1f}s start, {trim_end:.1f}s end)"

    return (
        f"Downloaded: {meta.artist} - {meta.title}\n"
        f"Saved to: {music_dir.subdir}/{final_path.name}{trim_info}\n"
        f"Genre: {music_dir.genre_tag}"
    )
