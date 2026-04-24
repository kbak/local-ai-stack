"""Chatterbox TTS engine — voice cloning model

Mirrors the kokoro/whisper pattern: load() once at startup, is_ready() reports
readiness, synthesize() runs the model. The CUDA arena is sized at warmup with
a real-length generate() so peak VRAM is known up-front.
"""
import io
import logging
from pathlib import Path
from typing import Optional

from . import audio_encode, config

logger = logging.getLogger(__name__)

_model = None  # type: ignore[var-annotated]


def load() -> None:
    global _model
    if _model is not None:
        return

    # torch is heavy; defer import until load() so module import stays cheap.
    import torch
    from chatterbox.tts import ChatterboxTTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Loading Chatterbox (device=%s, HF_HOME=%s)...", device, config.HF_HOME)
    _model = ChatterboxTTS.from_pretrained(device=device)
    logger.info("Chatterbox loaded. Sample rate: %d Hz. Warming up CUDA kernels...", _model.sr)
    try:
        # Realistic-length warmup so the CUDA allocator settles at peak working set.
        warmup_text = (
            "The quick brown fox jumps over the lazy dog. "
            "Voice cloning warmup pass to size the GPU memory arena."
        )
        _model.generate(warmup_text)
        logger.info("Chatterbox warmup complete.")
    except Exception:
        logger.exception("Chatterbox warmup failed (non-fatal)")


def is_ready() -> bool:
    return _model is not None


def list_voices() -> list[str]:
    if not config.VOICE_SAMPLES_DIR.exists():
        return []
    return sorted(p.stem for p in config.VOICE_SAMPLES_DIR.glob("*.wav"))


def resolve_voice(voice: Optional[str]) -> Optional[str]:
    """Map a voice identifier to an absolute .wav path, or None for default."""
    if not voice:
        return None
    p = Path(voice)
    if p.is_absolute() and p.suffix == ".wav":
        if not p.exists():
            raise FileNotFoundError(f"voice file not found: {p}")
        return str(p)
    candidate = config.VOICE_SAMPLES_DIR / f"{voice}.wav"
    if not candidate.exists():
        raise FileNotFoundError(f"voice not found: {candidate}")
    return str(candidate)


def synthesize(
    text: str,
    voice: Optional[str] = None,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
    response_format: str = "wav",
) -> bytes:
    """Generate audio bytes for `text`, optionally cloning `voice`.

    voice: filename stem under VOICE_SAMPLES_DIR (no .wav), or absolute path
           to a .wav file, or None for Chatterbox's built-in default voice.
    response_format: any value accepted by audio_encode (wav, ogg, opus, mp3,
           aac, m4a, flac, pcm). Defaults to wav (no re-encode).
    """
    import soundfile as sf

    if _model is None:
        raise RuntimeError("Chatterbox model not loaded")

    ref = resolve_voice(voice)
    kwargs = {"exaggeration": exaggeration, "cfg_weight": cfg_weight}
    if ref:
        kwargs["audio_prompt_path"] = ref

    wav = _model.generate(text, **kwargs)
    arr = wav.detach().cpu().numpy()
    if arr.ndim == 2:
        arr = arr.T  # soundfile expects (samples, channels)

    buf = io.BytesIO()
    sf.write(buf, arr, _model.sr, format="WAV", subtype="PCM_16")
    return audio_encode.encode(buf.getvalue(), response_format)
