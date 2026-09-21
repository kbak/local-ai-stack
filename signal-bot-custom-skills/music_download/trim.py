"""Trim silence, ads, and non-music content from the start and end of an MP3.

Strategy:
1. Extract up to 30s from start and 30s from end as separate clips
2. Transcribe each with Whisper — if speech found, send to LLM to judge ad/intro/outro
3. If no speech (pure music), run ffmpeg silencedetect on that clip
4. Combine decisions to produce final trim boundaries (trim_start_s, trim_end_s)
5. Apply trim with ffmpeg copy-codec (fast, no re-encode)
"""

import logging
import math
import re
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

PROBE_DURATION = 30      # seconds to sample at each end
SILENCE_THRESH = "-50dB" # silencedetect noise floor
SILENCE_MIN = 0.5        # minimum silence duration to detect (seconds)


def _get_duration(path: str) -> float:
    """Return audio duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", path,
        ],
        capture_output=True, text=True, check=True,
    )
    import json
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def _extract_clip(src: str, start: float, duration: float, dest: str):
    """Extract a clip from src into dest (mp3)."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-ss", str(start), "-t", str(duration),
            "-i", src, "-q:a", "0", dest,
        ],
        capture_output=True, check=True,
    )


def _transcribe(path: str) -> str:
    """Transcribe a short audio clip with Whisper. Returns text or empty string."""
    try:
        # Reuse the Whisper model from the transcribe module shipped with the bot
        import sys
        sys.path.insert(0, "/app")
        from transcribe import transcribe_audio
        return transcribe_audio(path)
    except Exception as e:
        logger.warning("Whisper transcription failed: %s", e)
        return ""


def _silence_seconds(path: str) -> float:
    """Detect trailing silence at the start of a clip. Returns seconds of silence."""
    result = subprocess.run(
        [
            "ffmpeg", "-i", path,
            "-af", f"silencedetect=noise={SILENCE_THRESH}:d={SILENCE_MIN}",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    output = result.stderr

    # Look for first silence_end (silence at the very start of the file)
    for line in output.splitlines():
        if "silence_end" in line:
            try:
                end = float(line.split("silence_end:")[1].split("|")[0].strip())
                return end
            except (IndexError, ValueError):
                pass
    return 0.0


def _llm_judge(clip_label: str, transcript: str) -> float:
    """Ask the LLM whether a clip is non-music (ad, intro, outro, silence).

    Returns seconds to trim (0.0 = keep everything, >0 = trim that many seconds).
    The clip is at most PROBE_DURATION seconds.
    """
    prompt = (
        f"This is a transcript of the {clip_label} {PROBE_DURATION} seconds of an audio file.\n\n"
        f"Transcript:\n{transcript}\n\n"
        f"Is this an advertisement, spoken intro, spoken outro, DJ announcement, "
        f"radio jingle, or other non-music content that should be trimmed? "
        f"If yes, estimate how many seconds should be trimmed (0 to {PROBE_DURATION}). "
        f"If no (it's music from the start), reply 0.\n\n"
        f"Reply with ONLY a number (integer or decimal). Nothing else."
    )
    try:
        from _shared.llm import chat

        result = chat(
            "You are an audio content analyst. Reply with a single number only.",
            prompt,
            max_tokens=8,
            temperature=0.0,
        )
        if not result:
            return 0.0
        import re
        m = re.search(r"\d+(?:\.\d+)?", result)
        if m:
            val = float(m.group())
            return min(val, PROBE_DURATION)
    except Exception as e:
        logger.error("LLM trim judge failed: %s", e)
    return 0.0


def parse_offset(value: str | float | int) -> float:
    """Parse nonnegative seconds, MM:SS, or HH:MM:SS."""
    text = str(value).strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?|\d+:\d{2}(?:\.\d+)?|\d+:\d{2}:\d{2}(?:\.\d+)?", text):
        raise ValueError("Trim offsets must be nonnegative seconds, MM:SS, or HH:MM:SS")
    parts = [float(part) for part in text.split(":")]
    if len(parts) > 1 and any(part >= 60 for part in parts[1:]):
        raise ValueError("Minutes/seconds after a colon must be less than 60")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    if not math.isfinite(seconds):
        raise ValueError("Trim offsets must be finite")
    return seconds


def trim_exact(src: str, dest: str, start: float, end: float) -> tuple[float, float]:
    """Remove explicit durations from the original audio; bypass automatic analysis."""
    start, end = parse_offset(start), parse_offset(end)
    total = _get_duration(src)
    duration = total - start - end
    if not math.isfinite(total) or duration <= 0:
        raise ValueError(f"Trim ({start:g}s start + {end:g}s end) would remove the entire {total:g}s track")
    # Re-encode for accurate offsets rather than MP3 frame-aligned stream copy.
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ss", str(start), "-t", str(duration),
         "-map", "0:a:0", "-c:a", "libmp3lame", "-q:a", "0", dest],
        capture_output=True, check=True,
    )
    actual = _get_duration(dest)
    if not math.isfinite(actual) or abs(actual - duration) > 0.15:
        raise RuntimeError(f"Trim verification failed: expected {duration:.3f}s, got {actual:.3f}s")
    return start, end


def trim_audio(src: str, dest: str) -> tuple[float, float]:
    """Trim non-music content from start and end of src, writing result to dest.

    Returns (trim_start_s, trim_end_s) for logging.
    """
    total = _get_duration(src)
    trim_start = 0.0
    trim_end = 0.0

    with tempfile.TemporaryDirectory() as tmp:
        start_clip = os.path.join(tmp, "start.mp3")
        end_clip = os.path.join(tmp, "end.mp3")

        probe = min(PROBE_DURATION, total / 2)  # don't overlap on short tracks

        # --- Probe start ---
        _extract_clip(src, 0, probe, start_clip)
        start_transcript = _transcribe(start_clip)

        if start_transcript.strip():
            logger.info("Start clip has speech (%d chars), asking LLM", len(start_transcript))
            trim_start = _llm_judge("first", start_transcript)
        else:
            logger.info("Start clip has no speech, using silence detection")
            trim_start = _silence_seconds(start_clip)

        # --- Probe end ---
        end_start_offset = max(0.0, total - probe)
        _extract_clip(src, end_start_offset, probe, end_clip)
        end_transcript = _transcribe(end_clip)

        if end_transcript.strip():
            logger.info("End clip has speech (%d chars), asking LLM", len(end_transcript))
            trim_end_probe = _llm_judge("last", end_transcript)
        else:
            logger.info("End clip has no speech, using silence detection")
            # For the end we reverse the clip so silencedetect finds leading silence = trailing silence of original
            reversed_clip = os.path.join(tmp, "end_rev.mp3")
            subprocess.run(
                ["ffmpeg", "-y", "-i", end_clip, "-af", "areverse", reversed_clip],
                capture_output=True, check=True,
            )
            trim_end_probe = _silence_seconds(reversed_clip)

        trim_end = trim_end_probe

        logger.info(
            "Trim decision: start=%.1fs end=%.1fs (total=%.1fs)",
            trim_start, trim_end, total,
        )

        # Apply trim — use stream copy for speed (no re-encode)
        duration = total - trim_start - trim_end
        if duration <= 0:
            logger.warning("Trim would remove entire file, skipping trim")
            import shutil
            shutil.copy2(src, dest)
            return 0.0, 0.0

        cmd = ["ffmpeg", "-y", "-ss", str(trim_start)]
        if trim_end > 0:
            cmd += ["-t", str(duration)]
        cmd += ["-i", src, "-c", "copy", dest]

        subprocess.run(cmd, capture_output=True, check=True)

    return trim_start, trim_end
