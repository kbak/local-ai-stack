"""Resolve song metadata from Spotify links, Shazam links, or LLM vision (screenshots)."""

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_SPOTIFY_TRACK_RE = re.compile(r"spotify\.com/track/([A-Za-z0-9]+)")
_SHAZAM_RE = re.compile(r"shazam\.com/(?:track|song)/(\d+)")


@dataclass
class SongMeta:
    artist: str
    title: str
    album: str = ""
    year: str = ""
    cover_url: str = ""
    genre_hint: str = ""      # from Spotify genre tags if available
    search_query: str = ""    # best YouTube search string


def _from_spotify(track_id: str) -> SongMeta | None:
    """Scrape artist/title from the public Spotify embed page (no credentials needed)."""
    try:
        resp = httpx.get(
            f"https://open.spotify.com/embed/track/{track_id}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
            follow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text

        # Spotify embed contains a JSON blob in a <script id="__NEXT_DATA__"> tag
        import json
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', html, re.DOTALL)
        if not m:
            logger.warning("Could not find __NEXT_DATA__ in Spotify embed")
            return None

        data = json.loads(m.group(1))
        # Navigate to track entity in the props
        entities = (
            data.get("props", {})
            .get("pageProps", {})
            .get("state", {})
            .get("data", {})
            .get("entity", {})
        )
        title = entities.get("name", "")
        artists = ", ".join(a["name"] for a in entities.get("artists", []))
        album = entities.get("albumName", "") or entities.get("album", {}).get("name", "")
        year = (entities.get("releaseDate", {}).get("isoString", "") or "")[:4]
        images = entities.get("albumOfTrack", {}).get("coverArt", {}).get("sources", [])
        cover_url = images[0].get("url", "") if images else ""

        if not title or not artists:
            logger.warning("Spotify embed parse incomplete: title=%r artists=%r", title, artists)
            return None

        meta = SongMeta(artist=artists, title=title, album=album, year=year, cover_url=cover_url)
        meta.search_query = _build_query(meta)
        logger.info("Spotify embed metadata: %s — %s", artists, title)
        return meta
    except Exception as e:
        logger.warning("Spotify embed fetch failed: %s", e)
        return None


def _from_shazam(track_id: str) -> SongMeta | None:
    """Fetch Shazam track metadata via the unofficial Shazam API."""
    try:
        resp = httpx.get(
            f"https://www.shazam.com/discovery/v5/en-US/US/web/-/track/{track_id}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()

        title = data.get("title", "")
        artist = data.get("subtitle", "")
        sections = data.get("sections", [])
        meta_section = next((s for s in sections if s.get("type") == "SONG"), {})
        meta_items = {m.get("title", "").lower(): m.get("text", "") for m in meta_section.get("metadata", [])}
        album = meta_items.get("album", "")
        year = meta_items.get("released", "")[:4] if meta_items.get("released") else ""
        cover_url = data.get("images", {}).get("coverarthq", "") or data.get("images", {}).get("coverart", "")

        # Shazam genre from hub or genres
        genre_hint = ""
        genres = data.get("genres", {})
        if genres:
            genre_hint = genres.get("primary", "")

        meta = SongMeta(
            artist=artist,
            title=title,
            album=album,
            year=year,
            cover_url=cover_url,
            genre_hint=genre_hint,
        )
        meta.search_query = _build_query(meta)
        logger.info("Shazam metadata: %s — %s", artist, title)
        return meta
    except Exception as e:
        logger.warning("Shazam metadata fetch failed: %s", e)
        return None


def _build_query(meta: SongMeta) -> str:
    """Build a YouTube search string that finds the right version."""
    parts = [meta.artist, meta.title]
    # Add 'official audio' or 'official video' to prefer official uploads
    return " ".join(p for p in parts if p) + " official audio"


def resolve_from_text(text: str) -> SongMeta | None:
    """Try to extract a SongMeta from a URL string."""
    # Spotify
    m = _SPOTIFY_TRACK_RE.search(text)
    if m:
        return _from_spotify(m.group(1))

    # Shazam
    m = _SHAZAM_RE.search(text)
    if m:
        return _from_shazam(m.group(1))

    return None


def resolve_from_image(image_b64: str, content_type: str) -> SongMeta | None:
    """Use the LLM (vision) to extract artist/title from a screenshot."""
    import config
    from strands import Agent

    try:
        model = config.make_model()
        agent = Agent(
            name="music-vision",
            model=model,
            system_prompt=(
                "You are a music metadata extractor. "
                "Given an image (screenshot of Shazam, Spotify, or a phone playing music), "
                "extract the song title and all artist names. "
                "Reply with ONLY two lines:\n"
                "ARTIST: <artist name(s), comma separated if multiple>\n"
                "TITLE: <song title>"
            ),
        )
        content = [
            {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{image_b64}"}},
            {"type": "text", "text": "Extract the artist and song title from this image."},
        ]
        result = str(agent(content))

        artist, title = "", ""
        for line in result.splitlines():
            if line.upper().startswith("ARTIST:"):
                artist = line.split(":", 1)[1].strip()
            elif line.upper().startswith("TITLE:"):
                title = line.split(":", 1)[1].strip()

        if artist and title:
            meta = SongMeta(artist=artist, title=title)
            meta.search_query = _build_query(meta)
            logger.info("Vision metadata: %s — %s", artist, title)
            return meta
    except Exception as e:
        logger.error("Vision metadata extraction failed: %s", e)
    return None
