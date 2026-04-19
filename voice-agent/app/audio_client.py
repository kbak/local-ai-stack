"""Thin client around audio-api's OpenAI-compatible endpoints."""

import logging
from typing import AsyncIterator

import httpx

from . import config

logger = logging.getLogger(__name__)


async def list_voices() -> list[str]:
    url = f"{config.AUDIO_API_URL.rstrip('/')}/v1/voices"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    if isinstance(data, dict):
        return list(data.get("voices") or data.get("data") or [])
    return list(data)


async def transcribe(audio_bytes: bytes, filename: str = "clip.webm", language: str | None = None) -> str:
    url = f"{config.AUDIO_API_URL.rstrip('/')}/v1/audio/transcriptions"
    data: dict = {}
    if language:
        data["language"] = language
    files = {"file": (filename, audio_bytes, "application/octet-stream")}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, files=files, data=data)
        resp.raise_for_status()
        return resp.json().get("text", "").strip()


async def synthesize_stream(
    text: str,
    voice: str | None = None,
    lang: str | None = None,
    speed: float | None = None,
    response_format: str = "mp3",
) -> AsyncIterator[bytes]:
    """Stream TTS audio sentence-by-sentence from audio-api.

    voice/lang/speed are omitted from the request when None so audio-api's
    server-side DEFAULT_VOICE/DEFAULT_LANG/DEFAULT_SPEED apply.
    """
    url = f"{config.AUDIO_API_URL.rstrip('/')}/v1/audio/speech"
    payload: dict = {
        "model": "kokoro",
        "input": text,
        "response_format": response_format,
        "stream": True,
    }
    if voice is not None:
        payload["voice"] = voice
    if lang is not None:
        payload["lang"] = lang
    if speed is not None:
        payload["speed"] = speed
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                if chunk:
                    yield chunk
