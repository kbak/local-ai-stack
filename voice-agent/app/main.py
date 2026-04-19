"""voice-agent entrypoint: FastAPI + WebSocket voice loop.

Protocol (all JSON except binary audio payloads):

Client → server:
  {"type": "audio", "format": "webm"}  then one binary WS frame with audio bytes
  {"type": "interrupt"}                 — user started speaking, cancel TTS
  {"type": "reset"}                     — clear conversation history

Server → client:
  {"type": "user_text", "text": "..."}       — what Whisper heard
  {"type": "agent_text", "text": "..."}      — what the agent said
  {"type": "audio_start", "format": "mp3"}   — audio stream starting
  <binary frame>                              — audio chunk (mp3)
  {"type": "audio_end"}                       — audio stream done
  {"type": "error", "message": "..."}
"""

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import agent, audio_client, config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("voice-agent")

app = FastAPI(title="voice-agent", version="1.0.0")

STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
def _startup() -> None:
    agent.build()


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/voices")
async def voices() -> JSONResponse:
    try:
        voices = await audio_client.list_voices()
    except Exception as e:
        logger.exception("Voice list failed")
        return JSONResponse({"voices": [], "default": config.TTS_VOICE, "error": str(e)}, status_code=200)
    return JSONResponse({"voices": voices, "default": config.TTS_VOICE})


AGENT_TIMEOUT_S = 60


async def _run_agent_and_stream_tts(ws: WebSocket, user_text: str, cancel: asyncio.Event, voice: str | None) -> None:
    """Run the agent, then stream TTS of its reply back over the websocket."""
    a = agent.build()

    try:
        result = await asyncio.wait_for(a.invoke_async(user_text), timeout=AGENT_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.warning("Agent timed out after %ss", AGENT_TIMEOUT_S)
        await ws.send_json({"type": "error", "message": "Agent took too long, giving up."})
        return
    except asyncio.CancelledError:
        logger.info("Agent cancelled by user")
        raise
    except Exception as e:
        logger.exception("Agent failed")
        await ws.send_json({"type": "error", "message": f"Agent error: {e}"})
        return

    reply = str(result).strip() if result is not None else ""
    if not reply:
        reply = "Sorry, I didn't get anything."

    await ws.send_json({"type": "agent_text", "text": reply})

    if cancel.is_set():
        return

    await ws.send_json({"type": "audio_start", "format": "mp3"})
    try:
        async for chunk in audio_client.synthesize_stream(reply, voice=voice, response_format="mp3"):
            if cancel.is_set():
                logger.info("TTS stream cancelled mid-flight")
                break
            await ws.send_bytes(chunk)
    except Exception as e:
        logger.exception("TTS stream failed")
        await ws.send_json({"type": "error", "message": f"TTS error: {e}"})
    finally:
        await ws.send_json({"type": "audio_end"})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    logger.info("WS connected")

    current_task: asyncio.Task | None = None
    cancel_event: asyncio.Event | None = None
    pending_format: str = "webm"
    selected_voice: str | None = None

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            text = msg.get("text")
            raw = msg.get("bytes")

            if text is not None:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    continue

                mtype = data.get("type")
                if mtype == "audio":
                    pending_format = data.get("format", "webm")
                    v = data.get("voice")
                    if v:
                        selected_voice = v
                elif mtype == "voice":
                    v = data.get("voice")
                    if v:
                        selected_voice = v
                elif mtype == "interrupt":
                    if cancel_event is not None:
                        cancel_event.set()
                    if current_task is not None and not current_task.done():
                        current_task.cancel()
                    logger.info("Interrupt received")
                elif mtype == "reset":
                    agent.reset_conversation()
                    await ws.send_json({"type": "reset_ok"})
                continue

            if raw is not None:
                # Audio payload arrived. Transcribe, then run agent + TTS.
                if current_task is not None and not current_task.done():
                    if cancel_event is not None:
                        cancel_event.set()
                    current_task.cancel()

                try:
                    user_text = await audio_client.transcribe(raw, filename=f"clip.{pending_format}")
                except Exception as e:
                    logger.exception("STT failed")
                    await ws.send_json({"type": "error", "message": f"STT error: {e}"})
                    continue

                if not user_text:
                    await ws.send_json({"type": "user_text", "text": ""})
                    continue

                await ws.send_json({"type": "user_text", "text": user_text})

                cancel_event = asyncio.Event()
                current_task = asyncio.create_task(
                    _run_agent_and_stream_tts(ws, user_text, cancel_event, selected_voice)
                )

    except WebSocketDisconnect:
        pass
    finally:
        if current_task is not None and not current_task.done():
            if cancel_event is not None:
                cancel_event.set()
            current_task.cancel()
        logger.info("WS disconnected")
