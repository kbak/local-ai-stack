"""Mem0 wrapper with a background write queue.

Writes (add_memory) return immediately and are processed asynchronously so
they never block a chat turn. Reads (search_memory, list, delete) are sync
since the agent needs the results inline.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any

from mem0 import Memory
from stack_shared.llm_model import resolve_model

from . import config

logger = logging.getLogger("memory-mcp.backend")

_memory: Memory | None = None
_resolved_model: str | None = None
_write_queue: queue.Queue = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


def _build_config(model_id: str) -> dict:
    return {
        "llm": {
            "provider": "openai",
            "config": {
                "model": model_id,
                "openai_base_url": config.LLM_BASE_URL,
                "api_key": config.LLM_API_KEY,
            },
        },
        "embedder": {
            "provider": "huggingface",
            "config": {
                "model": config.EMBED_MODEL,
                "embedding_dims": config.EMBED_DIMS,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": config.QDRANT_COLLECTION,
                "host": config.QDRANT_HOST,
                "port": config.QDRANT_PORT,
                "embedding_model_dims": config.EMBED_DIMS,
            },
        },
    }


def load() -> None:
    """Build the Mem0 instance and start the background writer.

    Called from FastAPI startup so model loading (bge-m3, ~1.2GB RAM) and
    Qdrant collection init happen before we accept requests.
    """
    global _memory, _resolved_model
    if _memory is not None:
        return
    # Mem0 bakes the LLM model into its internal client at construction time,
    # so we resolve once here. If llama-swap has no model loaded, this falls
    # back to the largest non-coder in /v1/models (llama-swap will auto-load
    # it on first chat call).
    _resolved_model = config.LLM_MODEL or resolve_model(base_url=config.LLM_BASE_URL)
    logger.info("Initializing Mem0 (llm=%s via %s, embed=%s, qdrant=%s:%s)...",
                _resolved_model, config.LLM_BASE_URL,
                config.EMBED_MODEL, config.QDRANT_HOST, config.QDRANT_PORT)
    _memory = Memory.from_config(_build_config(_resolved_model))
    _start_worker()
    logger.info("Mem0 ready.")


def is_ready() -> bool:
    return _memory is not None


def _start_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        t = threading.Thread(target=_worker_loop, daemon=True, name="memory-writer")
        t.start()
        _worker_started = True


def _worker_loop() -> None:
    while True:
        job = _write_queue.get()
        if job is None:
            break
        try:
            _do_add(**job)
        except Exception:
            logger.exception("Background memory write failed for job=%s", _redact(job))
        finally:
            _write_queue.task_done()


def _redact(job: dict) -> dict:
    out = dict(job)
    content = out.get("messages") or out.get("text") or ""
    if isinstance(content, str) and len(content) > 80:
        out["_preview"] = content[:80] + "..."
        out.pop("messages", None)
        out.pop("text", None)
    return out


def _do_add(*, messages: list[dict] | str, user_id: str, metadata: dict | None) -> None:
    assert _memory is not None
    result = _memory.add(messages, user_id=user_id, metadata=metadata or {})
    logger.info("Stored memory for user=%s: %s", user_id, result)


# ── Public API ──────────────────────────────────────────────────────────

def enqueue_add(messages: list[dict] | str, user_id: str, metadata: dict | None = None) -> None:
    """Queue a memory write. Returns immediately; Mem0's extractor runs in the background."""
    _write_queue.put({"messages": messages, "user_id": user_id, "metadata": metadata})


def search(query: str, user_id: str, limit: int = 5) -> list[dict[str, Any]]:
    assert _memory is not None
    result = _memory.search(query=query, user_id=user_id, limit=limit)
    # Mem0 returns {"results": [...]} in recent versions; normalize.
    if isinstance(result, dict) and "results" in result:
        return result["results"]
    return result  # type: ignore[return-value]


def list_all(user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    assert _memory is not None
    result = _memory.get_all(user_id=user_id, limit=limit)
    if isinstance(result, dict) and "results" in result:
        return result["results"]
    return result  # type: ignore[return-value]


def delete(memory_id: str) -> None:
    assert _memory is not None
    _memory.delete(memory_id=memory_id)


def pending_writes() -> int:
    return _write_queue.qsize()
