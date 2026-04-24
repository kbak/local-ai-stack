"""ffmpeg-based audio re-encoder shared by kokoro_engine and chatterbox_engine.

Both engines produce WAV/PCM internally; this helper converts to whatever the
caller asked for — including aac/m4a, the codec Signal uses for native voice
notes on iOS clients (ogg/opus also works and is what signal-cli prefers).
"""
import subprocess

# (mime_subtype, ffmpeg_args).  Subtype is what HTTP Content-Type maps to.
_FORMATS: dict[str, tuple[str, list[str]]] = {
    "wav":  ("wav",   []),  # passthrough
    "ogg":  ("ogg",   ["-c:a", "libopus", "-b:a", "24k", "-vbr", "on", "-application", "voip", "-f", "ogg"]),
    "opus": ("ogg",   ["-c:a", "libopus", "-b:a", "24k", "-vbr", "on", "-application", "voip", "-f", "ogg"]),
    "mp3":  ("mpeg",  ["-c:a", "libmp3lame", "-b:a", "64k", "-f", "mp3"]),
    "flac": ("flac",  ["-c:a", "flac", "-f", "flac"]),
    # ADTS-framed AAC is stream-safe (no seek needed); audio/aac is the MIME.
    # Fragmented MP4 for m4a so it can be piped without seeking.
    "aac":  ("aac",   ["-c:a", "aac", "-b:a", "64k", "-f", "adts"]),
    "m4a":  ("mp4",   ["-c:a", "aac", "-b:a", "64k", "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-f", "mp4"]),
    "pcm":  ("L16",   ["-f", "s16le", "-ac", "1", "-ar", "24000"]),
}

SUPPORTED_FORMATS = tuple(_FORMATS.keys())


def media_type_for(fmt: str) -> str:
    if fmt not in _FORMATS:
        raise ValueError(f"Unsupported format: {fmt}")
    return f"audio/{_FORMATS[fmt][0]}"


def encode(wav_bytes: bytes, output_format: str) -> bytes:
    """Re-encode WAV bytes to `output_format` via ffmpeg stdin/stdout.

    Pass-through for "wav".  Raises ValueError for unknown formats and
    CalledProcessError if ffmpeg fails.
    """
    if output_format not in _FORMATS:
        raise ValueError(f"Unsupported format: {output_format}")
    if output_format == "wav":
        return wav_bytes

    args = _FORMATS[output_format][1]
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", "pipe:0", *args, "pipe:1"],
        input=wav_bytes,
        capture_output=True,
        check=True,
    )
    return proc.stdout
