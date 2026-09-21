"""Conversation-scoped Qwen Image tools and Signal delivery.

The bot installs trusted context around each agent invocation. Tools expose
only prompts, sizes and opaque image IDs, never recipients or filesystem paths.
"""
from __future__ import annotations

import asyncio
import base64
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import time
import uuid

import httpx
from PIL import Image

log = logging.getLogger(__name__)
ROOT = Path(os.getenv("SIGNAL_IMAGE_DIR", "/app/data/images"))
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 16 * 1024 * 1024
KEEP_IMAGES = 20
RETENTION_SECONDS = 7 * 86400
SIZES = {"1024x1024", "768x1024", "1024x768"}


@dataclass
class Turn:
    signal: object
    recipient: str
    directory: Path
    calls: int = 0


_turn: ContextVar[Turn | None] = ContextVar("signal_image_turn", default=None)


def _directory(recipient: str) -> Path:
    return ROOT / hashlib.sha256(recipient.encode()).hexdigest()


def _prune(directory: Path) -> None:
    files = sorted(directory.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    for i, path in enumerate(files):
        if i >= KEEP_IMAGES or time.time() - path.stat().st_mtime > RETENTION_SECONDS:
            path.unlink(missing_ok=True)


def _png(data: bytes) -> bytes:
    if len(data) > MAX_BYTES:
        raise ValueError("Image exceeds the 20 MiB limit.")
    with Image.open(io.BytesIO(data)) as im:
        if im.width * im.height > MAX_PIXELS:
            raise ValueError("Image exceeds the 16 megapixel limit.")
        out = io.BytesIO()
        im.convert("RGBA").save(out, format="PNG")
    result = out.getvalue()
    if len(result) > MAX_BYTES:
        raise ValueError("Converted PNG exceeds the 20 MiB limit.")
    return result


def _save(directory: Path, data: bytes) -> str:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    image_id = uuid.uuid4().hex
    (directory / f"{image_id}.png").write_bytes(_png(data))
    temp = directory / "latest.tmp"
    temp.write_text(image_id)
    temp.replace(directory / "latest")
    _prune(directory)
    return image_id


def _reference(directory: Path, image_id: str) -> tuple[str, bytes]:
    if image_id == "latest":
        latest = directory / "latest"
        image_id = latest.read_text().strip() if latest.exists() else ""
    if not re.fullmatch(r"[a-f0-9]{32}", image_id):
        raise ValueError("No image reference available. Ask the user to attach an image.")
    path = directory / f"{image_id}.png"
    if not path.is_file() or time.time() - path.stat().st_mtime > RETENTION_SECONDS:
        raise ValueError("Image reference expired or is unavailable in this conversation. Ask for a new upload.")
    return image_id, path.read_bytes()


async def invoke_with_images(agent, text, images, signal, recipient):
    """Called inside the bot's cancellable agent task, including continuations."""
    directory = _directory(recipient)
    _prune(directory)
    references = []
    for block in images or []:
        try:
            references.append(_save(directory, block["image"]["source"]["bytes"]))
        except (KeyError, ValueError, OSError, Image.DecompressionBombError):
            log.warning("Could not retain image for editing", exc_info=True)
            references.append("unavailable")
    if references:
        text += "\n[Image references for this upload, in order: " + ", ".join(references) + "]"
        if "unavailable" in references:
            # Never silently edit an older image when the new upload failed.
            (directory / "latest").unlink(missing_ok=True)
    else:
        try:
            image_id, _ = _reference(directory, "latest")
            text += f"\n[Most recent image reference in this conversation: {image_id}]"
        except ValueError:
            pass
    token = _turn.set(Turn(signal, recipient, directory))
    try:
        return await agent.invoke_async([{"text": text}] + images if images else text)
    finally:
        _turn.reset(token)


async def _send(turn: Turn, message: str, data: bytes | None = None):
    recipient = turn.recipient
    if not recipient.startswith(("+", "group.")):
        recipient = await asyncio.to_thread(turn.signal._resolve_group_id, recipient)
    payload = {
        "number": turn.signal.number,
        "recipients": [recipient],
        "message": message,
    }
    if data is not None:
        payload["base64_attachments"] = [
            "data:image/png;filename=qwen-image.png;base64," + base64.b64encode(data).decode()
        ]
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{turn.signal.base_url}/v2/send", json=payload)
        response.raise_for_status()


async def run_image(prompt: str, size: str, image_id: str | None = None) -> str:
    turn = _turn.get()
    if turn is None:
        return "Image tools require an active Signal conversation."
    if size not in SIZES:
        return "Choose size 1024x1024, 768x1024, or 1024x768."
    if not prompt.strip() or len(prompt) > 8000:
        return "Provide a nonempty image prompt of at most 8000 characters."
    if turn.calls >= 2:
        return "Image request limit reached for this turn. Ask the user before generating more."
    try:
        reference = _reference(turn.directory, image_id)[1] if image_id is not None else None
    except ValueError as exc:
        return str(exc)
    turn.calls += 1
    try:
        await _send(turn, "Editing your image…" if reference else "Creating your image…")
    except httpx.HTTPError:
        log.warning("Image progress notification failed")

    base = os.getenv("SIGNAL_IMAGE_BASE_URL", os.getenv("LLM_BASE_URL", "https://llama.kacper.me/v1")).rstrip("/")
    key = os.getenv("SIGNAL_IMAGE_API_KEY", os.getenv("LLM_API_KEY", "vllm"))
    fields = {"model": "qwen-image-2.1", "prompt": prompt, "size": size}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(240, connect=15)) as client:
            kwargs = {"headers": {"Authorization": f"Bearer {key}"}}
            if reference is None:
                endpoint = "generations"
                kwargs["json"] = {**fields, "n": 1}
            else:
                endpoint = "edits"
                kwargs.update(data=fields, files=[("image[]", ("reference.png", reference, "image/png"))])
            # Bound base64 response size before decoding or storing it.
            async with client.stream("POST", f"{base}/images/{endpoint}", **kwargs) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES * 4 // 3 + 65536:
                        raise ValueError("Image backend response exceeded the size limit.")
            encoded = json.loads(body)["data"][0]["b64_json"]
            data = base64.b64decode(encoded, validate=True)
            result_id = _save(turn.directory, data)
            data = (turn.directory / f"{result_id}.png").read_bytes()
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, OSError, Image.DecompressionBombError):
        log.exception("Qwen image request failed")
        return "Image generation/editing failed. No image was sent. Do not retry automatically; ask the user to try again."
    try:
        await _send(turn, "", data)
    except httpx.HTTPError:
        log.exception("Generated image could not be delivered")
        return f"Image created (reference {result_id}), but Signal delivery failed. Do not claim it was sent."
    return f"Image successfully sent to this Signal conversation. Image reference: {result_id}. Use this reference for follow-up edits. Do not include filesystem paths or base64 in your reply."
