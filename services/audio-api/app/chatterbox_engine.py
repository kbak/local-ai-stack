"""Chatterbox V3 cloning, with an optional original English transformer.

The English and multilingual models share the vocoder and voice encoder.
Set CHATTERBOX_ENGLISH_MODEL=multilingual to use V3 for every language and
avoid loading the extra English transformer. Inference is serialized and
request conditioning is restored, including when generation fails.
"""
import copy
import io
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from . import audio_encode, config
from .inference import inference_lock
from .cloning_common import list_voices, resolve_voice, split_for_generation as _split_for_generation

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
    import inspect
    from chatterbox.tts import ChatterboxTTS, Conditionals, EnTokenizer
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS, MTLTokenizer
    from chatterbox.models.t3 import T3
    from chatterbox.models.t3.modules.t3_config import T3Config
    from chatterbox.models.s3gen import S3Gen
    from chatterbox.models.voice_encoder import VoiceEncoder
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file

    if config.CHATTERBOX_MULTILINGUAL_VERSION not in {"v2", "v3"}:
        raise ValueError("CHATTERBOX_MULTILINGUAL_VERSION must be v2 or v3")
    if config.CHATTERBOX_ENGLISH_MODEL not in {"original", "multilingual"}:
        raise ValueError("CHATTERBOX_ENGLISH_MODEL must be original or multilingual")
    if config.CHATTERBOX_MULTILINGUAL_VERSION == "v3" and "t3_model" not in inspect.signature(
        ChatterboxMultilingualTTS.from_pretrained
    ).parameters:
        raise RuntimeError("Chatterbox V3 requires the pinned upstream runtime; rebuild audio-api")
    multilingual_file = f"t3_mtl23ls_{config.CHATTERBOX_MULTILINGUAL_VERSION}.safetensors"

    # ── Download a reproducible set of shared and selected weights ────────
    needed = [
        "ve.safetensors",
        "s3gen.safetensors",
        multilingual_file,
        "grapheme_mtl_merged_expanded_v1.json",
        "conds.pt",
    ]
    if config.CHATTERBOX_ENGLISH_MODEL == "original":
        needed.extend(["tokenizer.json", "t3_cfg.safetensors"])
    paths = {
        f: hf_hub_download(repo_id=_REPO_ID, filename=f, revision=config.CHATTERBOX_REVISION)
        for f in needed
    }
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
    en_model = None
    if config.CHATTERBOX_ENGLISH_MODEL == "original":
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
    logger.info("Loading Multilingual T3 %s ...", config.CHATTERBOX_MULTILINGUAL_VERSION)
    t3_mtl = T3(T3Config.multilingual())
    t3_mtl_state = load_file(paths[multilingual_file])
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
    if is_ready():
        return

    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(
        "Loading Chatterbox %s (English=%s, device=%s)...",
        config.CHATTERBOX_MULTILINGUAL_VERSION, config.CHATTERBOX_ENGLISH_MODEL, device,
    )

    _en_model, _mtl_model = _build_models(device)

    try:
        _supported_languages = list(_mtl_model.get_supported_languages())
    except Exception:
        _supported_languages = []
    logger.info("Multilingual languages: %s", ",".join(_supported_languages) or "(unknown)")

    # Exercise both configured routes before the API accepts requests.
    synthesize("The quick brown fox jumps over the lazy dog.", language="en")
    synthesize("Dzień dobry. To jest próba głosu.", language="pl")
    logger.info("Chatterbox warmup complete.")


def is_ready() -> bool:
    return _mtl_model is not None and (
        _en_model is not None or config.CHATTERBOX_ENGLISH_MODEL == "multilingual"
    )


def supported_languages() -> list[str]:
    """Return the list of `language` codes accepted by `synthesize()`.

    Includes English regardless of which configured model handles it.
    """
    return sorted({"en", *_supported_languages})


@contextmanager
def _voice_conditioning(model, reference: str | None, exaggeration: float):
    """Keep per-request voice state isolated and restore the built-in default."""
    with inference_lock:
        saved = model.conds
        try:
            model.conds = copy.deepcopy(saved)
            if reference:
                model.prepare_conditionals(reference, exaggeration=exaggeration)
            yield
        finally:
            model.conds = saved


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
    language: ISO code. English uses the configured original or multilingual
              model; other languages use the multilingual model.
    response_format: any value accepted by audio_encode (wav, ogg, opus, mp3,
                     aac, m4a, flac, pcm). Defaults to wav (no re-encode).
    """
    import soundfile as sf

    if not is_ready():
        raise RuntimeError("Chatterbox models not loaded")

    lang = (language or "en").lower()
    if lang not in supported_languages():
        raise ValueError(
            f"unsupported language: {language!r}. "
            f"Supported: {', '.join(supported_languages())}"
        )

    ref = resolve_voice(voice)
    kwargs = {"exaggeration": exaggeration, "cfg_weight": cfg_weight}
    import torch

    model = _en_model if lang == "en" and _en_model is not None else _mtl_model
    sr = model.sr
    if model is _mtl_model:
        kwargs["language_id"] = lang
        # Match the current upstream V3 decoding default; v2 keeps its old value.
        kwargs["repetition_penalty"] = (
            1.2 if config.CHATTERBOX_MULTILINGUAL_VERSION == "v3" else 2.0
        )

    pieces = _split_for_generation(text)
    waves = []
    gap = None
    with _voice_conditioning(model, ref, exaggeration):
        for piece in pieces:
            waves.append(model.generate(piece, **kwargs).detach().cpu())
            if gap is None and len(pieces) > 1:
                gap = torch.zeros(
                    *waves[0].shape[:-1], int(sr * 0.2), dtype=waves[0].dtype,
                )
    if len(waves) == 1:
        wav = waves[0]
    else:
        joined: list = []
        for i, w in enumerate(waves):
            if i:
                joined.append(gap)
            joined.append(w)
        wav = torch.cat(joined, dim=-1)

    arr = wav.detach().cpu().numpy()
    if arr.ndim == 2:
        arr = arr.T  # soundfile expects (samples, channels)

    buf = io.BytesIO()
    sf.write(buf, arr, sr, format="WAV", subtype="PCM_16")
    return audio_encode.encode(buf.getvalue(), response_format)
