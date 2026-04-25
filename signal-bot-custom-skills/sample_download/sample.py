"""Voice-sample download skill — `/sample` entry point.

Downloads a short clip from a YouTube link and stores it as a `.wav` under
`VOICE_SAMPLES_DIR` for later use with audio-api's voice cloning.
"""

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from strands import tool

# Sibling skill modules
_SKILL_DIR = str(Path(__file__).parent)
if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)
# Sibling-skill `_shared/` package
_CUSTOM_SKILLS_ROOT = str(Path(__file__).parent.parent)
if _CUSTOM_SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _CUSTOM_SKILLS_ROOT)

from _shared.files import unique_path  # noqa: E402
from _shared.ytdlp import download_audio  # noqa: E402

import naming  # noqa: E402
import parse as parse_input  # noqa: E402

logger = logging.getLogger(__name__)


def _voice_dir() -> Path:
    return Path(os.getenv("VOICE_SAMPLES_DIR", "/app/voice-samples"))


def _slice_to_wav(src_mp3: str, start_s: float, length_s: float, dest_wav: str) -> None:
    """Cut [start, start+length] out of `src_mp3` and write a Chatterbox-friendly wav."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_s}",
        "-t", f"{length_s}",
        "-i", src_mp3,
        "-vn",
        "-ac", "1",
        "-ar", "24000",
        "-c:a", "pcm_s16le",
        dest_wav,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg slice failed: {proc.stderr.strip()[:300]}")


@tool
def download_sample(input: str, status_fn=None) -> str:
    """Download a short voice sample from a YouTube link and save it as `.wav`.

    Usage:
        /sample <youtube-url> <length>                  # length only; start = URL ?t= or 0
        /sample <youtube-url> <start> <length>          # explicit start
        /sample <youtube-url> <start> <length> <name>   # override the auto-name

    Timestamps may be `hh:mm:ss`, `mm:ss`, or `ss`. The sample is saved as
    `<firstname_lastname>.wav` under `VOICE_SAMPLES_DIR`. If the resulting name
    already exists, a numeric suffix is appended (e.g. `obama (2).wav`).

    Args:
        input: The full command tail — URL, timestamp(s), and optional name hint.
    """

    def status(msg: str):
        logger.info(msg)
        if status_fn:
            status_fn(msg)

    # --- 1. Parse ---
    try:
        parsed = parse_input.parse(input)
    except ValueError as e:
        return (
            f"Invalid input: {e}\n"
            "Usage: /sample <youtube-url> [start] <length> [name_hint]\n"
            "Example: /sample https://youtu.be/abc 1:30 10 barack_obama"
        )

    status(f"🔍 Parsed: start={parsed.start_s:.0f}s, length={parsed.length_s:.0f}s")

    voice_dir = _voice_dir()
    try:
        voice_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return f"Cannot write to {voice_dir}: {e}"

    with tempfile.TemporaryDirectory() as tmp:
        # --- 2. Download full audio ---
        status("⬇️ Downloading from YouTube…")
        raw_mp3 = os.path.join(tmp, "download.mp3")
        try:
            yt_artist, yt_title = download_audio(parsed.url, raw_mp3, timeout=180)
        except Exception as e:
            logger.exception("yt-dlp download failed")
            return f"Download failed: {e}"

        # --- 3. Slice to wav ---
        status(f"✂️ Extracting {parsed.length_s:.0f}s starting at {parsed.start_s:.0f}s…")
        sliced_wav = os.path.join(tmp, "sample.wav")
        try:
            _slice_to_wav(raw_mp3, parsed.start_s, parsed.length_s, sliced_wav)
        except Exception as e:
            logger.exception("ffmpeg slice failed")
            return f"Sample extraction failed: {e}"

        # --- 4. Resolve filename ---
        if parsed.name_hint:
            stem = naming.from_hint(parsed.name_hint)
            status(f"🏷️ Using name from hint: {stem}")
        else:
            status("🎤 Identifying speaker from title…")
            stem = naming.from_title(yt_title or "", yt_artist or "")
            status(f"🏷️ Auto-named: {stem}")

        final_path = unique_path(voice_dir, stem, ".wav")

        # --- 5. Move into place ---
        try:
            import shutil
            shutil.move(sliced_wav, final_path)
        except Exception as e:
            logger.exception("Move into voice dir failed")
            return f"Could not save sample: {e}"

    suffix_note = ""
    if final_path.stem != stem:
        suffix_note = (
            f"\n⚠️ `{stem}.wav` already existed — saved as `{final_path.name}` instead. "
            f"Delete the old file if you want to replace it."
        )

    return (
        f"💾 Saved voice sample: `{final_path.name}` ({parsed.length_s:.0f}s)"
        f"{suffix_note}\n"
        f"Use it with: `clone_voice(text=..., voice=\"{final_path.stem}\")`"
    )
