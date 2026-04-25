"""TTS skill — synthesize a Signal voice note via audio-api Chatterbox cloning."""

import logging
import os
import sys
from pathlib import Path

import httpx
from strands import tool

# Sibling-skill `_shared/` package (top-level import root for shared helpers)
_CUSTOM_SKILLS_ROOT = str(Path(__file__).parent.parent)
if _CUSTOM_SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _CUSTOM_SKILLS_ROOT)

from _shared import voice_match as match_mod  # noqa: E402
from _shared.skill_loader import load_sibling  # noqa: E402

# Namespaced sibling load — avoids collision if another skill ships a `lang.py`.
lang_mod = load_sibling(__file__, "lang")

logger = logging.getLogger(__name__)

# Soft-cap text length. Chatterbox runs ~150 wpm; ~2700 chars ≈ 3 minutes of speech.
MAX_TEXT_CHARS = 2700


def _audio_api_url() -> str:
    return os.getenv("AUDIO_API_URL", "http://audio-api:8088").rstrip("/")


class _AudioAPIUnavailable(Exception):
    """Raised when audio-api is unreachable (still loading, down, etc.)."""


def _list_voices() -> list[str]:
    """Fetch the current list of voice samples from audio-api.

    Raises _AudioAPIUnavailable on connection failure so the caller can show
    a clearer message than 'no voices' (which is misleading when the real
    issue is that audio-api hasn't finished loading yet).
    """
    try:
        resp = httpx.get(f"{_audio_api_url()}/v1/voices/clone", timeout=10)
        resp.raise_for_status()
        return resp.json().get("voices", [])
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
        raise _AudioAPIUnavailable(str(e)) from e
    except Exception as e:
        logger.warning("could not fetch voice list: %s", e)
        return []


def _clone_audio(text: str, voice: str | None, language: str) -> bytes:
    """POST to audio-api /v1/audio/clone and return the ogg bytes."""
    url = f"{_audio_api_url()}/v1/audio/clone"
    payload = {
        "text": text,
        "language": language,
        "response_format": "ogg",
    }
    if voice:
        payload["voice"] = voice

    resp = httpx.post(url, json=payload, timeout=600)
    if resp.status_code == 404:
        raise FileNotFoundError(resp.json().get("detail") or resp.text)
    if resp.status_code == 400:
        raise ValueError(resp.json().get("detail") or resp.text)
    resp.raise_for_status()
    return resp.content


@tool
def tts_clone(
    input: str,
    status_fn=None,
    signal=None,
    sender: str | None = None,
    target_author: str | None = None,
    target_ts: int | None = None,
    images: list | None = None,
) -> str:
    """Synthesize a Signal voice note from text using a cloned voice.

    Usage:
        /tts <voice-hint> <text>            (auto-detect language)
        /tts <lang> <voice-hint> <text>     (force language: en, pl, de, ...)
        /tts <name>.wav <text>              (explicit voice file, no fuzzy match)

    The first token is treated as a 2-letter ISO language code only if it's
    exactly two characters AND in the supported set. Otherwise, parsing
    proceeds straight to voice-hint matching (greedy, fuzzy). Whatever's
    left after the voice match is the text to synthesize.

    Args:
        input: Full command tail — optional language code, voice hint, text.
    """

    def status(msg: str):
        logger.info(msg)
        if status_fn:
            status_fn(msg)

    text_in = (input or "").strip()
    if not text_in:
        return (
            "Usage: /tts [lang] <voice-hint> <text>\n"
            "Example: /tts barack obama Hello there.\n"
            "Force language: /tts pl barack obama Cześć!\n"
            "Use `/voices` to list available samples."
        )

    tokens = text_in.split()

    # ── 1. Optional explicit language code as first token ────────────────
    forced_lang: str | None = None
    if tokens and lang_mod.is_lang_code(tokens[0]):
        forced_lang = tokens[0].lower()
        tokens = tokens[1:]

    if not tokens:
        return "Provide a voice hint and the text to synthesize."

    # ── 2. Voice match (greedy fuzzy) ─────────────────────────────────────
    try:
        available = _list_voices()
    except _AudioAPIUnavailable as e:
        logger.warning("audio-api unreachable: %s", e)
        return "🛠️ audio-api isn't ready yet (still loading). Try again in a few seconds."
    voice, remaining = match_mod.match_voice(tokens, available)

    if voice is None:
        # No match — be explicit so the user can fix it.
        sample_list = ", ".join(available[:12]) + ("…" if len(available) > 12 else "")
        return (
            f"No voice matches '{tokens[0]}'. "
            f"Available samples: {sample_list or '(none — use /sample to add one)'}"
        )

    if not remaining:
        return f"Found voice '{voice}' but no text to synthesize. Add the text after the voice hint."

    text = " ".join(remaining).strip()
    if len(text) > MAX_TEXT_CHARS:
        return (
            f"Text is {len(text)} chars; max is {MAX_TEXT_CHARS} (~3 min of speech). "
            f"Trim it or split across multiple /tts calls."
        )

    # ── 3. Language: forced or auto-detect ────────────────────────────────
    if forced_lang:
        language = forced_lang
        status(f"🔊 Voice: {voice} · 🌍 Language: {language} (forced)")
    else:
        language = lang_mod.detect(text)
        status(f"🔊 Voice: {voice} · 🌍 Language: {language} (auto)")

    # ── 4. Clone via audio-api ────────────────────────────────────────────
    try:
        ogg = _clone_audio(text, voice=voice, language=language)
    except FileNotFoundError as e:
        return f"Voice file not found: {e}"
    except ValueError as e:
        return f"Invalid request: {e}"
    except Exception as e:
        logger.exception("Cloning request failed")
        return f"Synthesis failed: {e}"

    # ── 5. Send voice note ────────────────────────────────────────────────
    if signal is not None and sender:
        try:
            if not signal.send_voice(sender, ogg):
                raise RuntimeError("signal send_voice returned failure")
        except Exception as e:
            logger.exception("Voice-note send failed")
            return f"Signal send failed: {e}"
        return ""

    # No signal client available (e.g. invoked by the agent loop, not a slash
    # command). Return a status string only — the agent can ask for /tts again.
    return (
        f"Synthesized {len(ogg) // 1024} KB but no Signal client available "
        f"to deliver it. Use /tts as a slash command."
    )
