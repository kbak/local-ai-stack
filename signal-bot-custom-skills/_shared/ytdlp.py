"""Thin client for the host yt-dlp service."""

import logging
import os

import httpx

logger = logging.getLogger(__name__)


def download_audio(query_or_url: str, dest_path: str, timeout: int = 180) -> tuple[str, str]:
    """Download best-quality audio via the host yt-dlp service.

    Writes the mp3 bytes to `dest_path`. Returns (artist, title) as reported
    by yt-dlp (either may be empty).
    """
    service_url = os.getenv("YTDLP_SERVICE_URL", "http://host.docker.internal:8200")
    logger.info("Calling yt-dlp service at %s for: %s", service_url, query_or_url)

    resp = httpx.post(
        f"{service_url}/download",
        json={"query": query_or_url},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"yt-dlp service error {resp.status_code}: {resp.text[:200]}")

    with open(dest_path, "wb") as f:
        f.write(resp.content)

    artist = resp.headers.get("X-Artist", "")
    title = resp.headers.get("X-Title", "")
    return artist, title
