"""Chatterbox TTS engine — voice cloning for English + 22 other languages.

Loads both the English-only ChatterboxTTS and the ChatterboxMultilingualTTS
sharing the same VoiceEncoder and S3Gen vocoder weights on the GPU. Only the
T3 transformer (~2.1 GB) and the tokenizer differ between the two — everything
else is reused, so total VRAM is ~5.5 GB instead of ~7 GB for two independent
instances.

Routing:
    language="en" (default)  → ChatterboxTTS
    language=<other>         → ChatterboxMultilingualTTS with that language_id

`load()` is called once at startup; both models warm up so the CUDA arena is
sized for peak working set.
"""
import io
import logging
from pathlib import Path
from typing import Optional

from . import audio_encode, config

logger = logging.getLogger(__name__)

_REPO_ID = "ResembleAI/chatterbox"

_en_model = None  # type: ignore[var-annotated]
_mtl_model = None  # type: ignore[var-annotated]
_supported_languages: list[str] = []


def _build_models(device: str):
    """Load shared components once and assemble both Chatterbox variants.

    Returns (en_model, mtl_model). The two share `ve` and `s3gen` Python
    objects (and thus the same GPU tensors), which halves the duplicate VRAM
    footprint compared to constructing them independently.
    """
    import torch
    from chatterbox.tts import ChatterboxTTS, Conditionals, EnTokenizer
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS, MTLTokenizer
    from chatterbox.models.t3 import T3
    from chatterbox.models.t3.modules.t3_config import T3Config
    from chatterbox.models.s3gen import S3Gen
    from chatterbox.models.voice_encoder import VoiceEncoder
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file

    # ── Download all needed files once each (HF cache dedupes) ────────────
    needed = [
        "ve.safetensors",
        "s3gen.safetensors",
        "tokenizer.json",
        "t3_cfg.safetensors",
        "t3_mtl23ls_v2.safetensors",
        "grapheme_mtl_merged_expanded_v1.json",
        "conds.pt",
    ]
    paths = {f: hf_hub_download(repo_id=_REPO_ID, filename=f) for f in needed}
    ckpt_dir = Path(paths["ve.safetensors"]).parent

    # ── Shared components (one copy on GPU, both models reference these) ──
    logger.info("Loading shared VoiceEncoder + S3Gen on %s ...", device)
    ve = VoiceEncoder()
    ve.load_state_dict(load_file(paths["ve.safetensors"]))
    ve.to(device).eval()

    s3gen = S3Gen()
    s3gen.load_state_dict(load_file(paths["s3gen.safetensors"]), strict=False)
    s3gen.to(device).eval()

    conds = None
    if (ckpt_dir / "conds.pt").exists():
        map_loc = torch.device("cpu") if device in ("cpu", "mps") else None
        conds = Conditionals.load(ckpt_dir / "conds.pt", map_location=map_loc).to(device)

    # ── English-only T3 + tokenizer ───────────────────────────────────────
    logger.info("Loading English T3 ...")
    t3_en = T3()
    t3_en_state = load_file(paths["t3_cfg.safetensors"])
    if "model" in t3_en_state.keys():
        t3_en_state = t3_en_state["model"][0]
    t3_en.load_state_dict(t3_en_state)
    t3_en.to(device).eval()
    en_tok = EnTokenizer(paths["tokenizer.json"])

    en_model = ChatterboxTTS(
        t3=t3_en, s3gen=s3gen, ve=ve, tokenizer=en_tok, device=device, conds=conds,
    )

    # ── Multilingual T3 + tokenizer ───────────────────────────────────────
    logger.info("Loading Multilingual T3 ...")
    t3_mtl = T3(T3Config.multilingual())
    t3_mtl_state = load_file(paths["t3_mtl23ls_v2.safetensors"])
    if "model" in t3_mtl_state.keys():
        t3_mtl_state = t3_mtl_state["model"][0]
    t3_mtl.load_state_dict(t3_mtl_state)
    t3_mtl.to(device).eval()
    mtl_tok = MTLTokenizer(paths["grapheme_mtl_merged_expanded_v1.json"])

    mtl_model = ChatterboxMultilingualTTS(
        t3=t3_mtl, s3gen=s3gen, ve=ve, tokenizer=mtl_tok, device=device, conds=conds,
    )

    return en_model, mtl_model


def load() -> None:
    global _en_model, _mtl_model, _supported_languages
    if _en_model is not None and _mtl_model is not None:
        return

    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Loading Chatterbox dual-model (device=%s, HF_HOME=%s)...", device, config.HF_HOME)

    _en_model, _mtl_model = _build_models(device)

    try:
        _supported_languages = list(_mtl_model.get_supported_languages())
    except Exception:
        _supported_languages = []
    logger.info("Multilingual languages: %s", ",".join(_supported_languages) or "(unknown)")

    # Warmup — one English pass via the EN model sizes the CUDA arena. The
    # multilingual T3 will JIT on first non-English request (~one slow call,
    # then steady state). This keeps startup fast.
    try:
        warmup_text = (
            "The quick brown fox jumps over the lazy dog. "
            "Voice cloning warmup pass to size the GPU memory arena."
        )
        _en_model.generate(warmup_text)
        logger.info("Chatterbox warmup complete.")
    except Exception:
        logger.exception("Chatterbox warmup failed (non-fatal)")


def is_ready() -> bool:
    return _en_model is not None and _mtl_model is not None


def list_voices() -> list[str]:
    if not config.VOICE_SAMPLES_DIR.exists():
        return []
    return sorted(p.stem for p in config.VOICE_SAMPLES_DIR.glob("*.wav"))


def supported_languages() -> list[str]:
    """Return the list of `language` codes accepted by `synthesize()`.

    Always includes 'en' (handled by the English-only model). Other codes
    come from the multilingual model's published language list.
    """
    return sorted({"en", *_supported_languages})


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
    language: str = "en",
) -> bytes:
    """Generate audio bytes for `text`, optionally cloning `voice`.

    voice: filename stem under VOICE_SAMPLES_DIR (no .wav), or absolute path
           to a .wav file, or None for Chatterbox's built-in default voice.
    language: ISO code. "en" routes to the English-only model; everything else
              goes through the multilingual model. Use `supported_languages()`
              to see what's available.
    response_format: any value accepted by audio_encode (wav, ogg, opus, mp3,
                     aac, m4a, flac, pcm). Defaults to wav (no re-encode).
    """
    import soundfile as sf

    if _en_model is None or _mtl_model is None:
        raise RuntimeError("Chatterbox models not loaded")

    lang = (language or "en").lower()
    if lang not in supported_languages():
        raise ValueError(
            f"unsupported language: {language!r}. "
            f"Supported: {', '.join(supported_languages())}"
        )

    ref = resolve_voice(voice)
    kwargs = {"exaggeration": exaggeration, "cfg_weight": cfg_weight}
    if ref:
        kwargs["audio_prompt_path"] = ref

    if lang == "en":
        wav = _en_model.generate(text, **kwargs)
        sr = _en_model.sr
    else:
        wav = _mtl_model.generate(text, language_id=lang, **kwargs)
        sr = _mtl_model.sr

    arr = wav.detach().cpu().numpy()
    if arr.ndim == 2:
        arr = arr.T  # soundfile expects (samples, channels)

    buf = io.BytesIO()
    sf.write(buf, arr, sr, format="WAV", subtype="PCM_16")
    return audio_encode.encode(buf.getvalue(), response_format)
