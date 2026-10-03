"""Select one cloning backend at startup; only the selected model is loaded."""

from . import config

if config.CLONE_BACKEND == "voxcpm2":
    from .voxcpm_engine import load, is_ready, synthesize, supported_languages
elif config.CLONE_BACKEND == "chatterbox":
    from .chatterbox_engine import load, is_ready, synthesize, supported_languages
else:
    raise ValueError("CLONE_BACKEND must be voxcpm2 or chatterbox")

from .cloning_common import list_voices
