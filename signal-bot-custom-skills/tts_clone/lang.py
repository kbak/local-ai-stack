"""Language detection + ISO-code helpers for tts_clone."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Languages Chatterbox supports (kept here so we can validate without a round-trip).
SUPPORTED = {
    "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi",
    "it", "ja", "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv",
    "sw", "tr", "zh",
}

# lingua-language-detector ISO codes — most match ours directly. A handful diverge:
_LINGUA_TO_ISO = {
    # lingua "CHINESE" -> "zh", normalisation handled below
    # Anything not in SUPPORTED falls back to English.
}

_detector = None  # type: ignore[var-annotated]


def _get_detector():
    """Lazy-build a lingua detector restricted to the languages Chatterbox knows."""
    global _detector
    if _detector is not None:
        return _detector

    try:
        from lingua import Language, LanguageDetectorBuilder
    except ImportError:
        logger.warning("lingua-language-detector not installed; auto-detect disabled")
        return None

    name_to_iso = {l.name: l.iso_code_639_1.name.lower() for l in Language.all()}
    wanted = [l for l in Language.all() if name_to_iso[l.name] in SUPPORTED]
    _detector = LanguageDetectorBuilder.from_languages(*wanted).with_low_accuracy_mode().build()
    return _detector


def detect(text: str) -> str:
    """Detect the language of `text`. Returns an ISO 639-1 code in SUPPORTED.

    Falls back to "en" if detection fails, returns an unknown code, or the
    detector is unavailable.
    """
    detector = _get_detector()
    if detector is None:
        return "en"
    try:
        result = detector.detect_language_of(text)
        if result is None:
            return "en"
        code = result.iso_code_639_1.name.lower()
        return code if code in SUPPORTED else "en"
    except Exception as e:
        logger.warning("lingua detection failed: %s", e)
        return "en"


def is_lang_code(token: str) -> bool:
    """True if `token` looks like a 2-letter ISO code we accept."""
    return len(token) == 2 and token.lower() in SUPPORTED
