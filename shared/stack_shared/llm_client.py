"""Shared OpenAI-compatible client + env defaults for stack services.

Services should call `get_client()` instead of `OpenAI(base_url=..., api_key=...)`
directly. That way base_url/api_key come from the same env vars across the
stack, and the httpx connection pool is reused within a process.
"""

from __future__ import annotations

import os
import threading

from openai import OpenAI

_DEFAULT_BASE_URL = "http://host.docker.internal:8080/v1"
_DEFAULT_API_KEY = "sk-no-key-required"

_lock = threading.Lock()
_clients: dict[tuple[str, str], OpenAI] = {}


def env_base_url() -> str:
    return (
        os.environ.get("LLM_BASE_URL")
        or os.environ.get("INFERENCE_BASE_URL")
        or _DEFAULT_BASE_URL
    )


def env_api_key() -> str:
    return (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("INFERENCE_API_KEY")
        or _DEFAULT_API_KEY
    )


def get_client(base_url: str | None = None, api_key: str | None = None) -> OpenAI:
    """Return a cached OpenAI client. Same (base_url, api_key) pair returns
    the same instance so the underlying httpx connection pool is reused."""
    bu = base_url or env_base_url()
    ak = api_key or env_api_key()
    key = (bu, ak)
    with _lock:
        client = _clients.get(key)
        if client is None:
            client = OpenAI(base_url=bu, api_key=ak)
            _clients[key] = client
    return client
