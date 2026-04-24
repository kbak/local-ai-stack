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
