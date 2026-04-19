import logging
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import config, kokoro_engine, whisper_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("audio-api")

app = FastAPI(title="audio-api", version="1.0.0")


@app.on_event("startup")
def _startup() -> None:
    whisper_engine.load()
    kokoro_engine.load()


@app.get("/health")
def health() -> Response:
    if whisper_engine.is_ready() and kokoro_engine.is_ready():
        return JSONResponse({"status": "ok"})
    return JSONResponse({"status": "loading"}, status_code=503)


@app.get("/v1/voices")
def voices() -> dict:
    return {
        "voices": kokoro_engine.list_voices(),
        "default": config.DEFAULT_VOICE,
        "lang": config.DEFAULT_LANG,
        "speed": config.DEFAULT_SPEED,
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
