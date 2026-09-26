import os
from pathlib import Path

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")

TTS_MODEL_DIR = Path(os.getenv("TTS_MODEL_DIR", "/app/kokoro-models"))
ONNX_PROVIDER = os.getenv("ONNX_PROVIDER", "CUDAExecutionProvider")

DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "af_heart")
DEFAULT_LANG = os.getenv("DEFAULT_LANG", "a")
DEFAULT_SPEED = float(os.getenv("DEFAULT_SPEED", "1.0"))

LANG_MAP = {"a": "en-us", "b": "en-gb"}

# Chatterbox (voice cloning TTS)
VOICE_SAMPLES_DIR = Path(os.getenv("VOICE_SAMPLES_DIR", "/app/voice-samples"))
HF_HOME = os.getenv("HF_HOME", "/app/hf-cache")
CHATTERBOX_REVISION = os.getenv(
    "CHATTERBOX_REVISION", "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
)
CHATTERBOX_MULTILINGUAL_VERSION = os.getenv("CHATTERBOX_MULTILINGUAL_VERSION", "v3")
# One multilingual transformer serves English and Polish; "original" is optional.
CHATTERBOX_ENGLISH_MODEL = os.getenv("CHATTERBOX_ENGLISH_MODEL", "multilingual")

# Exactly one cloning backend is resident on the audio GPU.
CLONE_BACKEND = os.getenv("CLONE_BACKEND", "voxcpm2")
VOXCPM_REVISION = "32279effe8c19989596f05d353d1447f51d9e915"
VOXCPM_MODEL_DIR = Path(os.getenv(
    "VOXCPM_MODEL_DIR", str(Path(HF_HOME) / "voxcpm2" / VOXCPM_REVISION)
))
VOXCPM_CFG_VALUE = float(os.getenv("VOXCPM_CFG_VALUE", "2.0"))
VOXCPM_INFERENCE_STEPS = int(os.getenv("VOXCPM_INFERENCE_STEPS", "10"))
VOXCPM_SEED = int(os.getenv("VOXCPM_SEED", "20260925"))
EXPECTED_AUDIO_GPU = os.getenv("EXPECTED_AUDIO_GPU", "NVIDIA GeForce RTX 5060 Ti")
