"""Reverse image search MCP server.

Tools:
  analyze_image(image_url)                     — VLM describes image → SearXNG → VLM synthesizes
  analyze_image_upload(b64, filename)          — upload to Litterbox first, then analyze
  reverse_image_search(image_url)              — Yandex + SauceNAO visual similarity search
  reverse_image_search_upload(b64, filename)   — upload to Litterbox first, then reverse-search

Use analyze_image for memes and photoshopped content.
Use reverse_image_search for originals where the image exists on the web.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from fastmcp import FastMCP

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

SAUCENAO_API_KEY = os.environ.get("SAUCENAO_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "").rstrip("/")
VLM_MODEL = os.environ.get("VLM_MODEL", "qwen3.6-35B-A3B-FP8")
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080")

_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# ── Litterbox upload ──────────────────────────────────────────────────────────

def _litterbox_upload(image_bytes: bytes, ext: str) -> str:
    """Upload image bytes to Litterbox with a 1-hour TTL. Returns public URL."""
    mime = _MIME.get(ext.lower(), "image/jpeg")
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "1h"},
            files={"fileToUpload": (f"image{ext}", image_bytes, mime)},
        )
        resp.raise_for_status()
    url = resp.text.strip()
    log.info("Litterbox upload: %s", url)
    return url


def _decode_upload(image_base64: str, filename: str) -> tuple[bytes, str]:
    """Decode base64 image and normalise extension. Raises ValueError on bad input."""
    try:
        image_bytes = base64.b64decode(image_base64)
    except Exception as exc:
        raise ValueError(f"Could not decode base64 image: {exc}") from exc
    ext = Path(filename).suffix.lower() or ".jpg"
    if ext not in _MIME:
        ext = ".jpg"
    return image_bytes, ext


# ── SauceNAO ──────────────────────────────────────────────────────────────────

def _saucenao(image_url: str) -> list[dict]:
    if not SAUCENAO_API_KEY:
        return []
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(
                "https://saucenao.com/search.php",
                params={
                    "url": image_url,
                    "api_key": SAUCENAO_API_KEY,
                    "output_type": 2,
                    "numres": 6,
                    "minsim": 50,
                },
            )
            resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("results", []):
            hdr = item.get("header", {})
            sim = float(hdr.get("similarity", 0))
            if sim < 50:
                continue
            d = item.get("data", {})
            urls = d.get("ext_urls") or []
            results.append({
                "similarity": sim,
                "url": urls[0] if urls else None,
                "title": d.get("title") or d.get("material"),
                "creator": d.get("creator") or d.get("author_name") or d.get("member_name"),
                "index": hdr.get("index_name"),
            })
        return sorted(results, key=lambda x: x["similarity"], reverse=True)
    except Exception as exc:
        log.warning("SauceNAO error: %s", exc)
        return []


# ── Yandex ────────────────────────────────────────────────────────────────────

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _yandex(image_url: str) -> dict:
    search_url = f"https://yandex.com/images/search?url={quote(image_url, safe='')}&rpt=imageview"
    out: dict = {"search_url": search_url, "entity": None, "tags": [], "sites": []}

    try:
        with httpx.Client(timeout=25, follow_redirects=True) as client:
            resp = client.get(
                search_url,
                headers={
                    "User-Agent": _UA,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )

        soup = BeautifulSoup(resp.text, "html.parser")

        for script in soup.find_all("script"):
            txt = script.string or ""
            if "CbirSites" not in txt and "cbir_sites" not in txt:
                continue
            for match in re.finditer(r'\{[^{}]{20,}\}', txt):
                try:
                    obj = json.loads(match.group())
                    sites = obj.get("CbirSites") or obj.get("cbir_sites") or []
                    for s in sites[:10]:
                        name = s.get("title") or s.get("domain") or s.get("url")
                        if name and name not in out["sites"]:
                            out["sites"].append(name)
                except Exception:
                    pass

        for el in soup.select("[class*='Tags-Item'], [class*='TagsItem']"):
            tag = el.get_text(strip=True)
            if tag and tag not in out["tags"]:
                out["tags"].append(tag)

        for el in soup.select("[class*='CbirSites-Item'], [class*='SitesItem']"):
            anchor = el.find("a")
            if anchor:
                title = anchor.get_text(strip=True)
                if title and title not in out["sites"]:
                    out["sites"].append(title)

        title_el = soup.find("title")
        if title_el:
            raw = title_el.get_text(strip=True)
            clean = re.sub(r'\s*[—–-]\s*Yandex.*$', '', raw).strip()
            if clean and clean.lower() not in ("", "yandex images"):
                out["entity"] = clean

        out["tags"] = out["tags"][:15]
        out["sites"] = out["sites"][:10]

    except Exception as exc:
        log.warning("Yandex error: %s", exc)
        out["error"] = str(exc)

    return out


# ── VLM + SearXNG chain ───────────────────────────────────────────────────────

_DESCRIBE_PROMPT = """/no_think
Look at this image carefully. Your job is to help identify everything in it.

1. List every distinct visual element (people, objects, brands, text, locations, art, meme templates, etc.)
2. For each element note whether you recognise it and how confident you are
3. Generate up to 4 focused web search queries to identify anything you are uncertain about:
   - For PEOPLE you don't recognise with certainty: describe them visually \
(e.g. "middle-aged Black man glasses suit skeptical expression meme") — never put a guessed name \
in a query; only use a name if you are certain who it is
   - For VEHICLES: describe make, colour, body style, and any visible badges or design details \
(e.g. "Ferrari light blue two-door concept car 2024 prancing horse badge")
   - For MEMES: include the template name if known, or describe the format
   - For other objects: be specific about brand, model, colour

Reply ONLY with a JSON object, no markdown fences:
{
  "elements": [
    {"description": "...", "identified_as": "..." or null, "confidence": "high|medium|low"}
  ],
  "context": "one sentence: what kind of image is this?",
  "search_queries": ["query1", "query2", ...]
}"""

_SYNTHESIZE_PROMPT = """/no_think
Web searches were run to identify the contents of an image. Results:

{search_context}

In 2-3 sentences, answer: what is in this image and who/what was identified?
- Only use names or titles that appear verbatim in the results above
- If the car model is named in the results, lead with that
- If the person is not named in the results, say so — do not guess
- Skip search metadata, speculation, and bullet lists — plain sentences only"""


def _vlm(messages: list[dict], max_tokens: int = 1024) -> str:
    with httpx.Client(timeout=90) as client:
        resp = client.post(
            f"{LLM_BASE_URL}/chat/completions",
            json={
                "model": VLM_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.2,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _vlm_describe(image_url: str) -> dict:
    raw = _vlm([
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": _DESCRIBE_PROMPT},
            ],
        }
    ])
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return {"elements": [], "context": raw, "search_queries": []}


def _searxng(query: str) -> list[dict]:
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{SEARXNG_URL}/search",
                params={"q": query, "format": "json", "categories": "general"},
            )
            resp.raise_for_status()
        return [
            {"title": r.get("title", ""), "content": r.get("content", ""), "url": r.get("url", "")}
            for r in resp.json().get("results", [])[:4]
        ]
    except Exception as exc:
        log.warning("SearXNG error for '%s': %s", query, exc)
        return []


def _vlm_synthesize(search_results: dict[str, list[dict]]) -> str:
    parts = []
    for query, results in search_results.items():
        parts.append(f'Search: "{query}"')
        for r in results:
            snippet = r["content"][:300] if r["content"] else "(no snippet)"
            parts.append(f"  • {r['title']}: {snippet}")
    search_context = "\n".join(parts) if parts else "(no search results)"

    # Text-only: no image passed so the model can't override search with its own visual
    # associations (which are often wrong for faces and new products).
    return _vlm(
        [
            {
                "role": "user",
                "content": _SYNTHESIZE_PROMPT.format(search_context=search_context),
            }
        ],
        max_tokens=200,
    )


# ── Format helpers ────────────────────────────────────────────────────────────

def _format_reverse(image_url: str, sauce: list[dict], yandex: dict) -> str:
    lines = [f"## Reverse image search\n**Image:** {image_url}\n"]

    if sauce:
        lines.append("### SauceNAO matches")
        for r in sauce:
            parts = [f"**{r['similarity']:.1f}%**"]
            if r.get("title"):
                parts.append(f"Title: {r['title']}")
            if r.get("creator"):
                parts.append(f"Creator: {r['creator']}")
            if r.get("index"):
                parts.append(f"Index: {r['index']}")
            if r.get("url"):
                parts.append(f"[link]({r['url']})")
            lines.append("- " + " | ".join(parts))
    elif SAUCENAO_API_KEY:
        lines.append("### SauceNAO: no matches above 50% similarity")
    else:
        lines.append("### SauceNAO: not configured (no SAUCENAO_API_KEY)")

    lines.append("")
    lines.append("### Yandex reverse image search")
    lines.append(f"[Open in browser]({yandex['search_url']})")

    if yandex.get("entity"):
        lines.append(f"\n**Identified as:** {yandex['entity']}")
    if yandex.get("tags"):
        lines.append(f"**Tags:** {', '.join(yandex['tags'])}")
    if yandex.get("sites"):
        lines.append("**Found on:**")
        for s in yandex["sites"]:
            lines.append(f"  - {s}")
    if yandex.get("error"):
        lines.append(
            f"\n_Yandex scraping failed ({yandex['error']}) — "
            "use the browser link above for full results._"
        )

    return "\n".join(lines)


# ── MCP tools ─────────────────────────────────────────────────────────────────

mcp = FastMCP("reverse-image-search")


@mcp.tool()
def analyze_image(image_url: str) -> str:
    """Identify people, objects, and memes in an image using VLM + web search.

    Best for photoshopped images and memes where the composite doesn't exist
    on the web. Sends the image to the local VLM (Qwen) which describes every
    element and generates search queries, executes those via SearXNG, then
    feeds the results back to Qwen for a final synthesized answer.

    image_url: publicly accessible HTTP/HTTPS URL to the image.
    """
    if not LLM_BASE_URL:
        return "Error: LLM_BASE_URL is not configured."

    description = _vlm_describe(image_url)
    log.info("VLM context: %s", description.get("context"))

    log.info("VLM queries: %s", description.get("search_queries"))
    search_results: dict[str, list[dict]] = {}
    for query in description.get("search_queries", [])[:4]:
        results = _searxng(query)
        if results:
            search_results[query] = results
            log.info("SearXNG '%s' → %d results: %s",
                     query, len(results), [r["title"][:60] for r in results])

    answer = _vlm_synthesize(search_results)

    lines = []
    if description.get("context"):
        lines.append(description["context"])
    if search_results:
        lines.append(answer)
    else:
        lines.append("No web search results found.")
    return "\n\n".join(lines)


@mcp.tool()
def analyze_image_upload(image_base64: str, filename: str = "image.jpg") -> str:
    """Upload a local/private image to Litterbox (1h TTL), then analyze with VLM + web search.

    Use when the image has no public URL (e.g. received via Signal or Telegram).

    image_base64: base64-encoded image bytes.
    filename: original filename — used to detect format (e.g. "photo.png").
    """
    try:
        image_bytes, ext = _decode_upload(image_base64, filename)
    except ValueError as exc:
        return str(exc)
    public_url = _litterbox_upload(image_bytes, ext)
    return analyze_image(public_url)


@mcp.tool()
def reverse_image_search(image_url: str) -> str:
    """Find the origin and identity of an image using its public URL.

    Queries SauceNAO (art, memes, anime) and Yandex Images (faces,
    celebrities, real-world photos). Best for unmodified images that
    exist somewhere on the web.

    image_url: a publicly accessible HTTP/HTTPS URL to the image.
    """
    sauce = _saucenao(image_url)
    yandex = _yandex(image_url)
    return _format_reverse(image_url, sauce, yandex)


@mcp.tool()
def reverse_image_search_upload(image_base64: str, filename: str = "image.jpg") -> str:
    """Upload a local/private image to Litterbox (1h TTL), then reverse-search it.

    Use when the image has no public URL (e.g. received via Signal or Telegram).

    image_base64: base64-encoded image bytes.
    filename: original filename — used to detect format (e.g. "photo.png").
    """
    try:
        image_bytes, ext = _decode_upload(image_base64, filename)
    except ValueError as exc:
        return str(exc)
    public_url = _litterbox_upload(image_bytes, ext)
    return reverse_image_search(public_url)


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if not LLM_BASE_URL:
        log.warning("LLM_BASE_URL not set — analyze_image tools will be unavailable")
    if not SAUCENAO_API_KEY:
        log.warning("SAUCENAO_API_KEY not set — SauceNAO matching disabled")

    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Mount

    port = int(os.environ.get("PORT", "8091"))
    http_app = mcp.http_app(path="/", transport="streamable-http")
    app = Starlette(routes=[Mount("/mcp", app=http_app)], lifespan=http_app.lifespan)
    uvicorn.run(app, host="0.0.0.0", port=port)
