"""Audio pipeline: per-turn voice cloning via audio-api + ffmpeg stitching."""

import logging
import os
import subprocess
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


def _audio_api_url() -> str:
    return os.getenv("AUDIO_API_URL", "http://audio-api:8088").rstrip("/")


def synthesize_turn(text: str, voice: str, language: str, out_path: Path, *, timeout: int = 600) -> bool:
    """Clone `text` in `voice` (Chatterbox stem) at `language`, write WAV to `out_path`.

    Asks audio-api for `wav` so the stitch step is a fast stream-copy concat.
    Returns True on success, False on any error (logged).
    """
    payload = {
        "text": text,
        "voice": voice,
        "language": language,
        "response_format": "wav",
    }
    try:
        resp = httpx.post(f"{_audio_api_url()}/v1/audio/clone", json=payload, timeout=timeout)
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        return True
    except Exception as e:
        logger.warning("[audio] clone failed for voice=%s lang=%s: %s", voice, language, e)
        return False


def stitch_to_ogg(wav_paths: list[Path], out_ogg: Path, *, gap_ms: int = 400) -> bool:
    """Concatenate WAVs with `gap_ms` of silence between, encode to OGG/Opus.

    Output format matches Signal's voice-note convention so signal-cli accepts
    it as a play-button bubble (not a file attachment).
    """
    if not wav_paths:
        return False

    inputs: list[str] = []
    n = len(wav_paths)
    for p in wav_paths:
        inputs += ["-i", str(p)]
    silence_idx = n
    inputs += ["-f", "lavfi", "-t", f"{gap_ms / 1000:.3f}", "-i", "anullsrc=r=24000:cl=mono"]

    chain: list[str] = []
    for i in range(n):
        chain.append(f"[{i}:a]")
        if i < n - 1:
            chain.append(f"[{silence_idx}:a]")
    filter_complex = "".join(chain) + f"concat=n={2 * n - 1}:v=0:a=1[out]"

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libopus", "-b:a", "32k",  # Signal voice-note bitrate range
        str(out_ogg),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("[audio] stitch failed: %s — stderr: %s", e, (e.stderr or "")[:500])
        return False
