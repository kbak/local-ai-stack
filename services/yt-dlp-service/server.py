"""Minimal yt-dlp download service.

Runs on the host where the browser session and cookies live.
The signal-bot container calls this to download audio as mp3.

Endpoints:
  POST /download  {"query": "artist title official audio"}
                  Returns the mp3 file as application/octet-stream.
                  Includes X-Title and X-Artist response headers.

Environment variables (all optional):
  YT_COOKIES      Path to Netscape cookies file (default: youtube_cookies.txt next to this script)
  PORT            Port to listen on (default: 8200)
"""

import logging
import os
import tempfile
from pathlib import Path

import shutil

import yt_dlp
import hmac

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("yt-dlp-service")

app = FastAPI()

# Optional bearer token. Set YTDLP_SERVICE_TOKEN in the environment to require
# callers to authenticate. Leave unset (or empty) to allow unauthenticated access.
_SERVICE_TOKEN = os.getenv("YTDLP_SERVICE_TOKEN", "")


def _check_auth(authorization: str = Header(default="")):
    if _SERVICE_TOKEN and not hmac.compare_digest(
        authorization.encode(), f"Bearer {_SERVICE_TOKEN}".encode()
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

COOKIES_FILE = os.getenv("YT_COOKIES", str(Path(__file__).parent / "youtube_cookies.txt"))


class DownloadRequest(BaseModel):
    query: str   # YouTube search query or direct URL


@app.post("/download")
async def download(req: DownloadRequest, background_tasks: BackgroundTasks, _: None = Depends(_check_auth)):
    logger.info("Download request: %s", req.query)

    tmp = tempfile.mkdtemp(prefix="ytdlp_")
    out_template = str(Path(tmp) / "download.%(ext)s")

    # Build js_runtimes — only accept native Linux binaries (skip /mnt/c/... Windows paths)
    js_runtimes = {}
    for runtime, binary in [("node", "node"), ("deno", "deno"), ("bun", "bun")]:
        path = shutil.which(binary)
        if path and not path.startswith("/mnt/c/"):
            js_runtimes[runtime] = {"path": path}
            break

    opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch1",
        # Allow yt-dlp to fetch the EJS challenge solver from GitHub (needed for YouTube sig solving)
        "remote_components": {"ejs:github"},
    }

    if js_runtimes:
        opts["js_runtimes"] = js_runtimes
        logger.info("JS runtime: %s", list(js_runtimes.keys()))

    if Path(COOKIES_FILE).exists():
        opts["cookiefile"] = COOKIES_FILE
        logger.info("Using cookies from %s", COOKIES_FILE)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(req.query, download=True)
            if "entries" in info:
                info = info["entries"][0]
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        logger.error("yt-dlp failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    mp3 = next(Path(tmp).glob("download*.mp3"), None)
    if not mp3:
        shutil.rmtree(tmp, ignore_errors=True)
        raise HTTPException(status_code=500, detail="yt-dlp did not produce an mp3 file")

    artist = info.get("artist") or info.get("uploader") or "" if info else ""
    title = info.get("track") or info.get("title") or "" if info else ""

    logger.info("Serving %s (%s - %s)", mp3.name, artist, title)

    # HTTP headers must be latin-1 — drop non-encodable chars (e.g. Polish diacritics)
    def _latin1_safe(s: str) -> str:
        return s.encode("latin-1", errors="replace").decode("latin-1")

    background_tasks.add_task(shutil.rmtree, tmp, ignore_errors=True)
    return FileResponse(
        path=str(mp3),
        media_type="audio/mpeg",
        filename=mp3.name,
        headers={
            "X-Artist": _latin1_safe(artist),
            "X-Title": _latin1_safe(title),
        },
    )


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8200"))
    uvicorn.run(app, host="0.0.0.0", port=port)
