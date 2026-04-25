"""List voice samples available for cloning."""

import logging
import os
from pathlib import Path

from strands import tool

logger = logging.getLogger(__name__)


def _voice_dir() -> Path:
    return Path(os.getenv("VOICE_SAMPLES_DIR", "/app/voice-samples"))


@tool
def list_voices() -> str:
    """List all `.wav` voice samples currently available for cloning.

    Each filename stem (without `.wav`) is what you pass as the `voice`
    argument to clone_voice. Use one of these names verbatim if you want to
    override the auto-detected speaker name in `/sample`.
    """
    d = _voice_dir()
    if not d.exists():
        return f"No voice-samples directory at {d}."

    samples = sorted(p.stem for p in d.glob("*.wav"))
    if not samples:
        return (
            f"No voice samples in {d} yet. "
            "Add one with `/sample <youtube-url> [start] <length>`."
        )

    lines = [f"🎤 {len(samples)} voice sample(s):"]
    lines.extend(f"  • {name}" for name in samples)
    return "\n".join(lines)
