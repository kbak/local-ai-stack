import io
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

from . import config

logger = logging.getLogger(__name__)

_kokoro = None

_MAX_CHARS = 400  # Kokoro's voice embedding caps at 510 phoneme tokens; 400 chars is a safe margin.


def load() -> None:
    global _kokoro
    if _kokoro is not None:
        return

    import onnxruntime as ort
    from kokoro_onnx import Kokoro

    available = ort.get_available_providers()
    use_cuda = config.ONNX_PROVIDER == "CUDAExecutionProvider" and "CUDAExecutionProvider" in available
    provider = "CUDAExecutionProvider" if use_cuda else "CPUExecutionProvider"
    model_file = config.TTS_MODEL_DIR / ("kokoro-v1.0.fp16.onnx" if use_cuda else "kokoro-v1.0.int8.onnx")
    voices_file = config.TTS_MODEL_DIR / "voices-v1.0.bin"

    os.environ["ONNX_PROVIDER"] = provider
    logger.info("Loading Kokoro ONNX %s (provider=%s)...", model_file.name, provider)
    _kokoro = Kokoro(str(model_file), str(voices_file))
    logger.info("Kokoro ONNX loaded. Warming up CUDA kernels...")
    try:
        # Full-length chunk so the ONNX Runtime CUDA arena sizes itself to the
        # real peak working set at startup, not on the first real request.
        warmup_text = ("The quick brown fox jumps over the lazy dog. " * 20)[:_MAX_CHARS]
        _kokoro.create(
            warmup_text,
            voice=config.DEFAULT_VOICE,
            speed=config.DEFAULT_SPEED,
            lang=config.LANG_MAP.get(config.DEFAULT_LANG, "en-us"),
        )
        logger.info("Kokoro warmup complete.")
    except Exception:
        logger.exception("Kokoro warmup failed (non-fatal)")


def is_ready() -> bool:
    return _kokoro is not None


def list_voices() -> list[str]:
    if _kokoro is None:
        return []
    try:
        return sorted(_kokoro.get_voices())
    except Exception:
        return []


def _resolve_lang(lang: str) -> str:
    return config.LANG_MAP.get(lang, lang)


def synthesize_wav(text: str, voice: str, lang: str, speed: float) -> tuple[bytes, int]:
    import soundfile as sf

    if _kokoro is None:
        raise RuntimeError("Kokoro model not loaded")

    samples, sample_rate = _kokoro.create(
        text,
        voice=voice,
        speed=speed,
        lang=_resolve_lang(lang),
    )

    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV")
    return buf.getvalue(), sample_rate


def _ffmpeg_encode(wav_bytes: bytes, output_format: str) -> bytes:
    """Encode WAV bytes to another format via ffmpeg stdin/stdout."""
    if output_format == "wav":
        return wav_bytes

    fmt_args = {
        "ogg": ["-c:a", "libopus", "-b:a", "24k", "-vbr", "on", "-application", "voip", "-f", "ogg"],
        "opus": ["-c:a", "libopus", "-b:a", "24k", "-vbr", "on", "-application", "voip", "-f", "ogg"],
        "mp3": ["-c:a", "libmp3lame", "-b:a", "64k", "-f", "mp3"],
        "flac": ["-c:a", "flac", "-f", "flac"],
        "pcm": ["-f", "s16le", "-ac", "1", "-ar", "24000"],
    }
    if output_format not in fmt_args:
        raise ValueError(f"Unsupported format: {output_format}")

    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", "pipe:0", *fmt_args[output_format], "pipe:1"],
        input=wav_bytes,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def synthesize(text: str, voice: str, lang: str, speed: float, response_format: str) -> bytes:
    """Synthesize text of any length, chunking to stay under Kokoro's 510-token cap.

    For short inputs this is a single synth + encode. For long briefs we split
    into sentences, further chunk any sentence over _MAX_CHARS, synthesize each
    to PCM, concatenate, then encode once.
    """
    import re

    import numpy as np
    import soundfile as sf

    if _kokoro is None:
        raise RuntimeError("Kokoro model not loaded")

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        sentences = [text]

    pieces: list[np.ndarray] = []
    sample_rate: int | None = None
    for sentence in sentences:
        for chunk in _chunk_long(sentence):
            try:
                samples, sr = _kokoro.create(
                    chunk, voice=voice, speed=speed, lang=_resolve_lang(lang)
                )
            except IndexError:
                logger.warning("Kokoro token overflow on chunk of %d chars, skipping", len(chunk))
                continue
            sample_rate = sr
            pieces.append(samples)

    if not pieces or sample_rate is None:
        raise RuntimeError("No audio synthesized")

    combined = np.concatenate(pieces)
    buf = io.BytesIO()
    sf.write(buf, combined, sample_rate, format="WAV")
    return _ffmpeg_encode(buf.getvalue(), response_format)


def _chunk_long(sentence: str, max_chars: int = _MAX_CHARS) -> list[str]:
    """Split a sentence that exceeds Kokoro's token cap along commas/whitespace."""
    if len(sentence) <= max_chars:
        return [sentence]

    import re
    # Try commas/semicolons/colons first, then fall back to whitespace.
    parts = re.split(r"(?<=[,;:])\s+", sentence)
    chunks: list[str] = []
    buf = ""
    for p in parts:
        if len(p) > max_chars:
            # Still too long — hard-split on whitespace.
            words = p.split()
            sub = ""
            for w in words:
                candidate = (sub + " " + w).strip()
                if len(candidate) > max_chars and sub:
                    chunks.append(sub)
                    sub = w
                else:
                    sub = candidate
            if sub:
                if buf:
                    chunks.append(buf); buf = ""
                chunks.append(sub)
            continue
        candidate = (buf + " " + p).strip()
        if len(candidate) > max_chars and buf:
            chunks.append(buf)
            buf = p
        else:
            buf = candidate
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c]


def synthesize_stream(
    text: str, voice: str, lang: str, speed: float, response_format: str
) -> Iterator[bytes]:
    """Stream audio by synthesizing one sentence at a time.

    Kokoro itself isn't a streaming model, but splitting by sentence gives
    perceptually streamed output — first audio lands in ~200ms instead of
    waiting for the full utterance.
    """
    import re

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        sentences = [text]

    for sentence in sentences:
        for chunk in _chunk_long(sentence):
            try:
                wav_bytes, _ = synthesize_wav(chunk, voice, lang, speed)
            except IndexError:
                logger.warning("Kokoro token overflow on chunk of %d chars, skipping", len(chunk))
                continue
            yield _ffmpeg_encode(wav_bytes, response_format)
