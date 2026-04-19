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
MIN_SENTENCE_CHARS = 12
MAX_SENTENCE_CHARS = 350
_SENTENCE_ENDERS = (".", "!", "?", "\n")


def _carve_sentence(buf: str) -> tuple[str | None, str]:
    """Pull one ready-to-speak sentence off the front of buf.

    Returns (sentence, remainder). sentence is None if nothing is ready yet.
    A sentence is 'ready' when we see a terminator after >= MIN_SENTENCE_CHARS,
    or the buffer grows past MAX_SENTENCE_CHARS (force a break).
    """
    if not buf:
        return None, buf

    for i, ch in enumerate(buf):
        if ch in _SENTENCE_ENDERS and i + 1 >= MIN_SENTENCE_CHARS:
            # Include trailing whitespace in the sentence we emit; skip for remainder.
            j = i + 1
            while j < len(buf) and buf[j].isspace():
                j += 1
            return buf[:j].strip(), buf[j:]

    if len(buf) >= MAX_SENTENCE_CHARS:
        # Force a break on the last whitespace to avoid mid-word cuts.
        cut = buf.rfind(" ", MIN_SENTENCE_CHARS, MAX_SENTENCE_CHARS)
        if cut == -1:
            cut = MAX_SENTENCE_CHARS
        return buf[:cut].strip(), buf[cut:].lstrip()

    return None, buf


async def _tts_worker(
    ws: WebSocket,
    queue: asyncio.Queue,
    voice: str | None,
    cancel: asyncio.Event,
) -> None:
    """Pull sentences off the queue, synthesize, forward bytes to WS."""
    # Tell client to open MediaSource right away — browser setup overlaps with
    # first Kokoro synth, shaving ~50-150ms off perceived time-to-first-audio.
    await ws.send_json({"type": "audio_start", "format": "mp3"})
    sent_audio = False
    try:
        while True:
            sentence = await queue.get()
            if sentence is None:  # sentinel
                break
            if cancel.is_set():
                continue  # drain queue silently
            try:
                async for chunk in audio_client.synthesize_stream(
                    sentence, voice=voice, response_format="mp3"
                ):
                    if cancel.is_set():
                        break
                    await ws.send_bytes(chunk)
                    sent_audio = True
            except Exception as e:
                logger.exception("TTS synthesis failed for sentence")
                await ws.send_json({"type": "error", "message": f"TTS error: {e}"})
                break
    finally:
        try:
            await ws.send_json({"type": "audio_end"})
        except Exception:
            pass


async def _run_agent_and_stream_tts(ws: WebSocket, user_text: str, cancel: asyncio.Event, voice: str | None) -> None:
    """Stream agent tokens; dispatch sentences to TTS as they complete."""
    a = agent.build()

    tts_queue: asyncio.Queue = asyncio.Queue()
    tts_task = asyncio.create_task(_tts_worker(ws, tts_queue, voice, cancel))

    full_reply_parts: list[str] = []
    buffer = ""

    async def _consume_stream() -> None:
        nonlocal buffer
        async for event in a.stream_async(user_text):
            if cancel.is_set():
                break
            delta = event.get("data") if isinstance(event, dict) else None
            if not delta:
                continue
            buffer += delta
            while True:
                sentence, buffer = _carve_sentence(buffer)
                if sentence is None:
                    break
                full_reply_parts.append(sentence)
                await tts_queue.put(sentence)

    try:
        await asyncio.wait_for(_consume_stream(), timeout=AGENT_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.warning("Agent timed out after %ss", AGENT_TIMEOUT_S)
        await ws.send_json({"type": "error", "message": "Agent took too long, giving up."})
        await tts_queue.put(None)
        await tts_task
        return
    except asyncio.CancelledError:
        logger.info("Agent cancelled by user")
        cancel.set()
        await tts_queue.put(None)
        await tts_task
        raise
    except Exception as e:
        logger.exception("Agent failed")
        await ws.send_json({"type": "error", "message": f"Agent error: {e}"})
        await tts_queue.put(None)
        await tts_task
        return

    # Flush any trailing buffered text as a final sentence.
    tail = buffer.strip()
    if tail:
        full_reply_parts.append(tail)
        await tts_queue.put(tail)

    reply = " ".join(full_reply_parts).strip() or "Sorry, I didn't get anything."
    await ws.send_json({"type": "agent_text", "text": reply})

    await tts_queue.put(None)
    await tts_task


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
