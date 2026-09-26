"""Pinned VoxCPM2 cloning, using the settings from the listening comparison."""

import io
import logging

import numpy as np
import soundfile as sf

from . import audio_encode, config
from .cloning_common import resolve_voice, split_for_generation
from .inference import inference_lock

logger = logging.getLogger(__name__)
_model = None
_ready = False

# From the pinned VoxCPM2 model card. The model infers language from the text;
# this list validates the existing API's language field, without translating it.
_LANGUAGES = "ar my zh da nl en fi fr de el he hi id it ja km ko lo ms no pl pt ru es sw sv tl th tr vi".split()
_ASSETS = (
    "config.json", "model.safetensors", "audiovae.pth", "tokenizer.json",
    "tokenizer_config.json", "special_tokens_map.json", "tokenization_voxcpm2.py",
)


def load() -> None:
    global _model, _ready
    if _ready:
        return
    from huggingface_hub import snapshot_download
    from voxcpm import VoxCPM

    if config.VOXCPM_INFERENCE_STEPS < 1 or config.VOXCPM_CFG_VALUE <= 0:
        raise ValueError("VoxCPM inference steps and CFG must be positive")
    directory = config.VOXCPM_MODEL_DIR
    if not all((directory / filename).is_file() for filename in _ASSETS):
        snapshot_download(
            "openbmb/VoxCPM2", revision=config.VOXCPM_REVISION,
            local_dir=str(directory), allow_patterns=list(_ASSETS),
        )
    logger.info("Loading VoxCPM2 revision %s on cuda:0...", config.VOXCPM_REVISION)
    _model = VoxCPM.from_pretrained(
        str(directory), load_denoiser=False, optimize=False,
        local_files_only=True, device="cuda:0",
    )
    # Warm both languages before readiness, using the same path as requests.
    synthesize("Good morning. The speech service is ready.", language="en")
    synthesize("Dzień dobry. Synteza mowy jest gotowa.", language="pl")
    _ready = True
    logger.info("VoxCPM2 warmup complete.")


def is_ready() -> bool:
    return _ready


def supported_languages() -> list[str]:
    return sorted(_LANGUAGES)


def synthesize(
    text: str, voice: str | None = None, exaggeration: float = 0.5,
    cfg_weight: float = 0.5, response_format: str = "wav", language: str = "en",
) -> bytes:
    """Render 48 kHz speech, optionally using an existing reference WAV.

    The legacy Chatterbox exaggeration/cfg_weight fields remain accepted for
    client compatibility; VoxCPM uses VOXCPM_CFG_VALUE and the reference style.
    """
    if _model is None:
        raise RuntimeError("VoxCPM2 is not loaded")
    if not text.strip():
        raise ValueError("text must not be empty")
    if (language or "en").lower() not in _LANGUAGES:
        raise ValueError(f"unsupported language: {language!r}")
    if response_format not in audio_encode.SUPPORTED_FORMATS:
        raise ValueError(f"unsupported response_format: {response_format!r}")
    reference = resolve_voice(voice)
    if exaggeration != 0.5 or cfg_weight != 0.5:
        logger.info("Chatterbox controls do not apply to VoxCPM2; using configured VoxCPM CFG")
    pieces = split_for_generation(text)
    waves = []
    sample_rate = _model.tts_model.sample_rate
    # VoxCPM reuses generation caches and seeds global RNGs. Serialize with
    # Kokoro and Whisper as well, to keep workspace usage bounded on the 5060.
    with inference_lock:
        for index, piece in enumerate(pieces):
            samples = np.asarray(_model.generate(
                text=piece, reference_wav_path=reference,
                cfg_value=config.VOXCPM_CFG_VALUE,
                inference_timesteps=config.VOXCPM_INFERENCE_STEPS,
                normalize=False, denoise=False, max_len=1024,
                retry_badcase_max_times=1, seed=config.VOXCPM_SEED + index,
            ), dtype=np.float32)
            if samples.ndim != 1 or samples.size == 0 or not np.isfinite(samples).all():
                raise RuntimeError("VoxCPM2 returned invalid audio")
            if waves:
                waves.append(np.zeros(int(sample_rate * 0.2), dtype=np.float32))
            waves.append(samples)
    buffer = io.BytesIO()
    sf.write(buffer, np.concatenate(waves), sample_rate, format="WAV", subtype="PCM_16")
    return audio_encode.encode(buffer.getvalue(), response_format)
