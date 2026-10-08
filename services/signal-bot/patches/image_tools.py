"""Conversation-scoped Qwen Image tools and Signal delivery.

The bot installs trusted context around each agent invocation. Tools expose
only prompts, sizes and opaque image IDs, never recipients or filesystem paths.
"""
from __future__ import annotations

import asyncio
import base64
from contextvars import ContextVar
from dataclasses import dataclass, field
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
KEEP_MESSAGES = 200
SIZES = {"1024x1024", "768x1024", "1024x768"}


@dataclass
class ImageSelection:
    attachments: list
    is_reply: bool = False
    thumbnail: bool = False
    references: list[str] | None = None
    thumbnails: list = field(default_factory=list)
    source: str = "upload"


class ImageBlocks(list):
    """Vision blocks with trusted routing metadata; metadata never enters the model API."""

    def __init__(self, selection: ImageSelection):
        super().__init__()
        self.selection = selection


@dataclass
class Turn:
    signal: object
    recipient: str
    directory: Path
    calls: int = 0
    selected_images: list[str] | None = None


_turn: ContextVar[Turn | None] = ContextVar("signal_image_turn", default=None)


def _directory(recipient: str) -> Path:
    return ROOT / hashlib.sha256(recipient.encode()).hexdigest()


def _image_attachments(attachments: list) -> list[dict]:
    return [
        {"id": att["id"], "contentType": att["contentType"]}
        for att in attachments
        if isinstance(att, dict)
        and att.get("contentType") in ("image/jpeg", "image/png", "image/gif", "image/webp")
        and isinstance(att.get("id"), str)
        and re.fullmatch(r"[A-Za-z0-9_.-]{1,256}", att["id"])
    ]


def _message_index(recipient: str) -> list[dict]:
    try:
        entries = json.loads((_directory(recipient) / "messages.json").read_text())
        return [entry for entry in entries if time.time() - entry["saved_at"] <= RETENTION_SECONDS]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def remember_image_message(message: dict, recipient: str) -> None:
    """Index authorized messages before group activation, without downloading their images."""
    attachments = _image_attachments(message.get("attachments") or [])
    timestamp = message.get("timestamp")
    authors = message.get("sender_aliases") or [message.get("sender")]
    authors = [author for author in authors if isinstance(author, str) and author]
    if not attachments or not timestamp or not authors:
        return
    directory = _directory(recipient)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    entries = [entry for entry in _message_index(recipient)
               if not (entry["timestamp"] == str(timestamp) and set(entry["authors"]) & set(authors))]
    entries.append({"timestamp": str(timestamp), "authors": authors,
                    "attachments": attachments, "saved_at": time.time()})
    temp = directory / "messages.tmp"
    temp.write_text(json.dumps(entries[-KEEP_MESSAGES:]))
    temp.replace(directory / "messages.json")


def select_message_images(message: dict, recipient: str) -> ImageSelection:
    """Resolve this upload or this exact quote, never a different conversation image."""
    quote = message.get("quote")
    uploads = _image_attachments(message.get("attachments") or [])
    if uploads or not quote:
        return ImageSelection(uploads, is_reply=bool(quote))
    authors = {quote.get(key) for key in ("author", "authorNumber", "authorUuid") if quote.get(key)}
    thumbnails = []
    for attachment in quote.get("attachments") or []:
        thumbnail = attachment.get("thumbnail") or {}
        thumbnails.extend(_image_attachments([{**thumbnail, "contentType":
                            thumbnail.get("contentType") or attachment.get("contentType")}]))
    for entry in reversed(_message_index(recipient)):
        if entry["timestamp"] == str(quote.get("id")) and authors.intersection(entry["authors"]):
            return ImageSelection(entry["attachments"], is_reply=True, thumbnails=thumbnails, source="quote")
    return ImageSelection(thumbnails, is_reply=True, thumbnail=bool(thumbnails), source="quote")


def fetch_message_images(selection: ImageSelection, fetch) -> ImageBlocks:
    images = ImageBlocks(selection)
    for attachment in selection.attachments:
        block = fetch(attachment)
        if block:
            images.append(block)
    if not images and selection.thumbnails:
        selection.thumbnail = True
        for attachment in selection.thumbnails:
            block = fetch(attachment)
            if block:
                images.append(block)
    return images


def reply_context(text: str, quote: dict | None) -> str:
    quoted = ((quote or {}).get("text") or "").strip()
    if quoted:
        quoted = quoted[:500] + ("…" if len(quoted) > 500 else "")
        return f"[replying to: {quoted}]\n{text}".strip()
    return text


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


def read_conversation_image(image_id: str) -> tuple[str, bytes]:
    """Read only an opaque reference belonging to the trusted current turn."""
    turn = _turn.get()
    if turn is None:
        raise ValueError("Image references require an active Signal conversation.")
    return _turn_reference(turn, image_id)


def _turn_reference(turn: Turn, image_id: str) -> tuple[str, bytes]:
    # A quote changes what "latest" means, not which historical images may be
    # explicitly referenced (e.g. comparing this photo with an earlier one).
    if image_id == "latest" and turn.selected_images is not None:
        if not turn.selected_images:
            raise ValueError("No image is available for this message. Use an explicit earlier image reference only if the user intends it; otherwise ask for the intended attachment.")
        image_id = turn.selected_images[-1]
    return _reference(turn.directory, image_id)


def identify_direct(func, source, images, signal, recipient):
    """Trusted slash-command entry point; never exposed as an agent tool."""
    directory = _directory(recipient)
    _prune(directory)
    selection = getattr(images, "selection", None)
    selected = [] if selection and (selection.is_reply or selection.attachments) else None
    if images:
        source = _save(directory, images[0]["image"]["source"]["bytes"])
        selected = [source]
    token = _turn.set(Turn(signal, recipient, directory, selected_images=selected))
    try:
        return func(source=source or "latest")
    finally:
        _turn.reset(token)


async def invoke_with_images(agent, text, images, signal, recipient, selection=None):
    """Called inside the bot's cancellable agent task, including continuations."""
    directory = _directory(recipient)
    _prune(directory)
    selection = selection or getattr(images, "selection", None)
    references = []
    for block in images or []:
        try:
            references.append(_save(directory, block["image"]["source"]["bytes"]))
        except (KeyError, ValueError, OSError, Image.DecompressionBombError):
            log.warning("Could not retain image for editing", exc_info=True)
            references.append("unavailable")
    if references:
        label = "quoted thumbnail" if selection and selection.thumbnail else (
            "quoted image" if selection and selection.source == "quote" else "upload")
        text += f"\n[Image references for this {label}, in order: " + ", ".join(references) + "]"
        if "unavailable" in references:
            # Never silently edit an older image when the new upload failed.
            (directory / "latest").unlink(missing_ok=True)
    if selection and references:
        selection.references = [ref for ref in references if ref != "unavailable"]
    has_selection = selection and (selection.is_reply or selection.attachments)
    if has_selection and selection.references is None:
        selection.references = []
    selected = selection.references if has_selection else None
    if has_selection and not selected:
        text += "\n[No image was resolved from the quoted/current message. Do not silently substitute another image. Conversation history remains available; use an explicit earlier reference only if the user intends it, or ask which image they mean.]"
    elif not references and not has_selection:
        try:
            image_id, _ = _reference(directory, "latest")
            text += f"\n[No new image is attached. Most recent retained image reference: {image_id}. Use conversation history to resolve earlier references; do not assume this image is the subject of the current request.]"
        except ValueError:
            pass
    token = _turn.set(Turn(signal, recipient, directory, selected_images=selected))
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
        reference = _turn_reference(turn, image_id)[1] if image_id is not None else None
    except ValueError as exc:
        return str(exc)
    turn.calls += 1
    try:
        await _send(turn, "Editing your image…" if reference else "Creating your image…")
    except httpx.HTTPError:
        log.warning("Image progress notification failed")

    base = os.getenv("SIGNAL_IMAGE_BASE_URL", os.getenv("LLM_BASE_URL", "http://host.docker.internal:8080/v1")).rstrip("/")
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
            if turn.selected_images is not None:
                turn.selected_images.append(result_id)
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
