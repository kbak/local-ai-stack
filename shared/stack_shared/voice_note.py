"""Synthesize a long text brief into Signal voice notes.

Pipeline: strip markdown → chunk at section boundaries → synthesize each chunk
via audio-api (ogg/opus) → POST to signal-api as base64 attachments.

Chunking prefers the `---` horizontal rules in our briefs so each section becomes
its own voice message. Sections that still exceed MAX_CHARS are split at paragraph
boundaries, then at sentence boundaries as a last resort.
"""

from __future__ import annotations

import base64
import logging
import os
import re

import httpx

from .signal_client import send_message

log = logging.getLogger(__name__)

MAX_CHARS = 3500  # ~3-4 min of audio at Kokoro's default speed
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0)


# ── markdown stripping ───────────────────────────────────────────────────────

_RE_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_RE_ITALIC_UNDER = re.compile(r"(?<!_)__(.+?)__(?!_)", re.DOTALL)
_RE_ITALIC_STAR = re.compile(r"(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)")
_RE_CODE_FENCE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)
_RE_CODE_INLINE = re.compile(r"`([^`]+)`")
_RE_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_RE_HR = re.compile(r"^\s*[-*_]{3,}\s*$", re.MULTILINE)
_RE_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_RE_MULTISPACE = re.compile(r"[ \t]+")
_RE_MULTINEWLINE = re.compile(r"\n{3,}")


def strip_markdown(text: str) -> str:
    """Remove markdown syntax so TTS reads natural prose."""
    text = _RE_CODE_FENCE.sub("", text)
    text = _RE_LINK.sub(r"\1", text)
    text = _RE_BOLD.sub(r"\1", text)
    text = _RE_ITALIC_UNDER.sub(r"\1", text)
    text = _RE_ITALIC_STAR.sub(r"\1", text)
    text = _RE_CODE_INLINE.sub(r"\1", text)
    text = _RE_HEADING.sub("", text)
    text = _RE_HR.sub("", text)
    text = _RE_BULLET.sub("", text)
    text = _RE_MULTISPACE.sub(" ", text)
    text = _RE_MULTINEWLINE.sub("\n\n", text)
    return text.strip()


# ── chunking ─────────────────────────────────────────────────────────────────


def _split_section_if_needed(section: str, max_chars: int) -> list[str]:
    """Split one section into chunks <= max_chars by paragraphs, then sentences."""
    if len(section) <= max_chars:
        return [section]

    out: list[str] = []
    buf = ""
    for para in section.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(para) > max_chars:
            # Paragraph itself too long — split at sentence ends.
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for s in sentences:
                if len(buf) + len(s) + 1 > max_chars and buf:
                    out.append(buf.strip())
                    buf = ""
                buf = (buf + " " + s).strip() if buf else s
            continue
        if len(buf) + len(para) + 2 > max_chars and buf:
            out.append(buf.strip())
            buf = ""
        buf = (buf + "\n\n" + para) if buf else para
    if buf.strip():
        out.append(buf.strip())
    return out


def chunk_for_voice(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Split a stripped brief into voice-note-sized chunks.

    Prefers horizontal-rule boundaries in the source (top-level sections).
    """
    # We already stripped --- to empty lines, but a stripped brief keeps the
    # paragraph gap. Re-split on the original marker by calling this before
    # strip_markdown would be cleaner; instead we split on 2+ blank lines, which
    # is what _RE_HR + _RE_MULTINEWLINE produces from ---.
    raw_sections = re.split(r"\n\s*\n\s*\n+", text)
    sections = [s.strip() for s in raw_sections if s.strip()]
    if not sections:
        sections = [text.strip()]

    chunks: list[str] = []
    for sec in sections:
        chunks.extend(_split_section_if_needed(sec, max_chars))
    return chunks


# ── audio-api client ─────────────────────────────────────────────────────────


def synthesize_opus(
    text: str,
    *,
    voice: str,
    audio_api_url: str,
    speed: float = 1.0,
) -> bytes:
    """POST text to audio-api and return ogg/opus bytes."""
    resp = httpx.post(
        f"{audio_api_url}/v1/audio/speech",
        json={
            "model": "kokoro",
            "input": text,
            "voice": voice,
            "response_format": "opus",
            "speed": speed,
        },
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.content


# ── send ─────────────────────────────────────────────────────────────────────


def send_voice_note(
    ogg_bytes: bytes,
    *,
    signal_api_url: str,
    signal_number: str,
    recipient: str,
) -> None:
    """POST a single ogg/opus blob to signal-api as a voice note attachment."""
    encoded = base64.standard_b64encode(ogg_bytes).decode()
    resp = httpx.post(
        f"{signal_api_url}/v2/send",
        json={
            "message": "",
            "number": signal_number,
            "recipients": [recipient],
            "base64_attachments": [f"data:audio/ogg;filename=voice.ogg;base64,{encoded}"],
        },
        timeout=60,
    )
    resp.raise_for_status()


def send_text_and_voice_brief(
    text: str,
    *,
    signal_api_url: str,
    signal_number: str,
    recipient: str,
    voice: str | None = None,
    audio_api_url: str | None = None,
) -> None:
    """Send the text brief, then synthesize and send voice-note chunks after it."""
    send_message(text, signal_api_url=signal_api_url, signal_number=signal_number, recipient=recipient)

    voice = voice or os.environ.get("TTS_VOICE", "am_onyx")
    audio_api_url = audio_api_url or os.environ.get("AUDIO_API_URL", "http://audio-api:8088")

    stripped = strip_markdown(text)
    chunks = chunk_for_voice(stripped)
    log.info("Synthesizing %d voice-note chunk(s) for brief (%d chars total)", len(chunks), len(stripped))

    for i, chunk in enumerate(chunks, 1):
        try:
            ogg = synthesize_opus(chunk, voice=voice, audio_api_url=audio_api_url)
        except Exception:
            log.exception("TTS failed for chunk %d/%d — skipping", i, len(chunks))
            continue
        try:
            send_voice_note(
                ogg,
                signal_api_url=signal_api_url,
                signal_number=signal_number,
                recipient=recipient,
            )
            log.info("Voice note %d/%d sent (%d chars, %d bytes)", i, len(chunks), len(chunk), len(ogg))
        except Exception:
            log.exception("Failed to send voice note %d/%d", i, len(chunks))
