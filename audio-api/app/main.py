import logging
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from . import audio_encode, chatterbox_engine, config, kokoro_engine, whisper_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("audio-api")


# ── MCP tool surface ───────────────────────────────────────────────────
# Chatterbox is the voice-cloning model — exposed as an MCP tool so LibreChat
# agents can clone a voice on demand. Whisper/Kokoro stay REST-only because
# LibreChat already speaks to them via its built-in OpenAI-compat speech config.

mcp = FastMCP("audio-api")


@mcp.tool()
def clone_voice(
    text: str,
    voice: str = "",
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
    response_format: str = "wav",
) -> dict:
    """Synthesize speech that clones a target voice using Chatterbox.

    Use this when the user wants speech rendered in a specific voice — either
    a named sample (e.g. "joe") or an absolute path to a reference .wav file.
    Returns base64-encoded audio. For the built-in default voice (no cloning),
    pass an empty `voice`.

    Args:
        text: The text to synthesize. Required.
        voice: Filename stem under the voice-samples directory (e.g. "joe"
               for joe.wav), OR an absolute .wav path, OR empty for the
               built-in default voice.
        exaggeration: 0.0–1.0. Higher values push more expressive prosody.
        cfg_weight: Classifier-free guidance weight, 0.0–1.0. Higher values
                    track the reference voice more strictly.
        response_format: "wav" (default), "mp3", "ogg" / "opus" (Signal voice
                    notes via signal-cli), "aac" / "m4a" (iOS-native voice
                    memos), "flac", or "pcm".
    """
    import base64

    if not text.strip():
        return {"error": "text must not be empty"}
    if response_format not in audio_encode.SUPPORTED_FORMATS:
        return {
            "error": f"unsupported response_format: {response_format}",
            "supported": list(audio_encode.SUPPORTED_FORMATS),
        }
    try:
        audio_bytes = chatterbox_engine.synthesize(
            text=text,
            voice=voice or None,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
            response_format=response_format,
        )
    except FileNotFoundError as e:
        return {"error": str(e), "available_voices": chatterbox_engine.list_voices()}
    except Exception as e:
        logger.exception("clone_voice failed")
        return {"error": str(e)}

    return {
        "format": response_format,
        "media_type": audio_encode.media_type_for(response_format),
        "voice": voice or "default",
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "bytes": len(audio_bytes),
    }


@mcp.tool()
def list_clone_voices() -> dict:
    """List the voice samples available for clone_voice."""
    return {
        "voices": chatterbox_engine.list_voices(),
        "voice_dir": str(config.VOICE_SAMPLES_DIR),
    }


# ── FastAPI app (REST + mounted MCP) ───────────────────────────────────
# Build the MCP sub-app once so we can hoist its lifespan into FastAPI's.
# FastMCP's streamable-http app manages a task group that MUST be entered via
# its own lifespan context; without this, POSTs to /mcp/mcp fail with
# "Task group is not initialized". Same gotcha as memory-mcp.
mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    whisper_engine.load()
    kokoro_engine.load()
    chatterbox_engine.load()
    async with mcp_app.router.lifespan_context(mcp_app):
        yield


app = FastAPI(title="audio-api", version="1.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> Response:
    if (
        whisper_engine.is_ready()
        and kokoro_engine.is_ready()
        and chatterbox_engine.is_ready()
    ):
        return JSONResponse({"status": "ok"})
    return JSONResponse(
        {
            "status": "loading",
            "whisper": whisper_engine.is_ready(),
            "kokoro": kokoro_engine.is_ready(),
            "chatterbox": chatterbox_engine.is_ready(),
        },
        status_code=503,
    )


@app.get("/v1/voices")
def voices() -> dict:
    return {
        "voices": kokoro_engine.list_voices(),
        "default": config.DEFAULT_VOICE,
        "lang": config.DEFAULT_LANG,
        "speed": config.DEFAULT_SPEED,
    }


@app.get("/v1/voices/clone")
def clone_voices() -> dict:
    return {
        "voices": chatterbox_engine.list_voices(),
        "voice_dir": str(config.VOICE_SAMPLES_DIR),
    }


_CONTENT_TYPE_TO_SUFFIX = {
    "audio/aac": ".aac",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/flac": ".flac",
}


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form("whisper-1"),
    language: str | None = Form(None),
    response_format: str = Form("json"),
) -> Response:
    data = await file.read()
    suffix = _CONTENT_TYPE_TO_SUFFIX.get(file.content_type or "", "")
    if not suffix and file.filename:
        suffix = "." + file.filename.rsplit(".", 1)[-1] if "." in file.filename else ""
    if not suffix:
        suffix = ".bin"

    try:
        result = whisper_engine.transcribe_bytes(data, suffix=suffix, language=language)
    except Exception as e:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=500, detail=str(e))

    if response_format == "text":
        return PlainTextResponse(result["text"])
    if response_format == "verbose_json":
        return JSONResponse(result)
    return JSONResponse({"text": result["text"]})


class SpeechRequest(BaseModel):
    model: str = "kokoro"
    input: str
    voice: str = Field(default_factory=lambda: config.DEFAULT_VOICE)
    response_format: Literal["wav", "ogg", "opus", "mp3", "flac", "pcm"] = "ogg"
    speed: float = Field(default_factory=lambda: config.DEFAULT_SPEED)
    lang: str = Field(default_factory=lambda: config.DEFAULT_LANG)
    stream: bool = False


_MEDIA_TYPES = {
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "pcm": "audio/L16",
}


@app.post("/v1/audio/speech")
def speech(req: SpeechRequest) -> Response:
    if not req.input.strip():
        raise HTTPException(status_code=400, detail="input must not be empty")

    media_type = _MEDIA_TYPES[req.response_format]

    try:
        if req.stream:
            gen = kokoro_engine.synthesize_stream(
                req.input, req.voice, req.lang, req.speed, req.response_format
            )
            return StreamingResponse(gen, media_type=media_type)

        audio = kokoro_engine.synthesize(
            req.input, req.voice, req.lang, req.speed, req.response_format
        )
        return Response(content=audio, media_type=media_type)
    except Exception as e:
        logger.exception("Synthesis failed")
        raise HTTPException(status_code=500, detail=str(e))


class CloneRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    exaggeration: float = 0.5
    cfg_weight: float = 0.5
    response_format: Literal["wav", "ogg", "opus", "mp3", "flac", "aac", "m4a", "pcm"] = "wav"


@app.post("/v1/audio/clone")
def clone(req: CloneRequest) -> Response:
    """Synthesize cloned-voice audio. Returns the chosen format directly."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    try:
        audio_bytes = chatterbox_engine.synthesize(
            text=req.text,
            voice=req.voice,
            exaggeration=req.exaggeration,
            cfg_weight=req.cfg_weight,
            response_format=req.response_format,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Voice cloning failed")
        raise HTTPException(status_code=500, detail=str(e))
    return Response(
        content=audio_bytes,
        media_type=audio_encode.media_type_for(req.response_format),
    )


# Mount FastMCP at /mcp. External path is /mcp/mcp because FastMCP's
# streamable-http app serves its handler at its own internal /mcp.
app.mount("/mcp", mcp_app)
