"""Bound GPU inference across the shared audio models."""

from threading import RLock

# Chatterbox mutates conditioning during generation; the other engines also
# need workspace headroom on the shared 16 GB card. Reentrant for chunk retries.
inference_lock = RLock()


def validate_audio_gpu() -> None:
    """Fail before loading any audio model if GPU isolation is incorrect."""
    import os
    import torch
    from . import config

    if not os.environ.get("CUDA_VISIBLE_DEVICES"):
        raise RuntimeError("Audio requires an explicit CUDA_VISIBLE_DEVICES setting")
    if torch.cuda.device_count() != 1:
        raise RuntimeError("Exactly one GPU must be visible to audio-api")
    actual = torch.cuda.get_device_name(0)
    if actual != config.EXPECTED_AUDIO_GPU:
        raise RuntimeError(f"Audio GPU must be {config.EXPECTED_AUDIO_GPU}, got {actual}")
