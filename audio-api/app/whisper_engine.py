import logging
import tempfile
from pathlib import Path

from faster_whisper import WhisperModel

from . import config

logger = logging.getLogger(__name__)

_model: WhisperModel | None = None


def load() -> None:
    global _model
    if _model is not None:
        return
    logger.info(
        "Loading Whisper model '%s' (device=%s, compute=%s)...",
        config.WHISPER_MODEL,
        config.WHISPER_DEVICE,
        config.WHISPER_COMPUTE_TYPE,
    )
    _model = WhisperModel(
        config.WHISPER_MODEL,
        device=config.WHISPER_DEVICE,
        compute_type=config.WHISPER_COMPUTE_TYPE,
    )
    logger.info("Whisper model loaded. Warming up CUDA kernels...")
    _warmup()
    logger.info("Whisper warmup complete.")


def _warmup() -> None:
    """Force CUDA kernel JIT/autotune by transcribing a short silent clip."""
    import numpy as np
    import soundfile as sf

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        silence = np.zeros(16000, dtype=np.float32)
        sf.write(tmp_path, silence, 16000)
        segments, _ = _model.transcribe(tmp_path)
        list(segments)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def is_ready() -> bool:
    return _model is not None


def transcribe_bytes(data: bytes, suffix: str = ".bin", language: str | None = None) -> dict:
    if _model is None:
        raise RuntimeError("Whisper model not loaded")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp.flush()
        tmp_path = tmp.name

    try:
        segments, info = _model.transcribe(tmp_path, language=language)
        seg_list = list(segments)
        text = " ".join(s.text for s in seg_list).strip()
        logger.info(
            "Transcribed %d bytes: lang=%s (%.0f%%), %d chars",
            len(data),
            info.language,
            info.language_probability * 100,
            len(text),
        )
        return {
            "text": text,
            "language": info.language,
            "language_probability": info.language_probability,
            "duration": info.duration,
        }
    finally:
        Path(tmp_path).unlink(missing_ok=True)
