"""Resolve which model to send chat requests to.

Policy: pick the largest model currently loaded in llama-swap that isn't a
coder/autocomplete model. Coder models are pinned on the 5060 Ti for VS Code
tab-complete and are not meant for chat/agent work. If nothing suitable is
loaded, fall back to an env var or to the first non-coder model advertised by
/v1/models - llama-swap will load it on demand when the chat request lands.

All stack services should call `resolve_model()` instead of reading
`LLM_MODEL` directly. That way adding/renaming/removing a model in
`llama-swap.yaml` doesn't break every caller.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Iterable

import httpx

log = logging.getLogger(__name__)

_DEFAULT_CODER_PATTERN = re.compile(r"coder", re.IGNORECASE)
_PARAM_COUNT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)B", re.IGNORECASE)

_CACHE_TTL_SECONDS = 60.0
_cache_lock = threading.Lock()
_cache: tuple[float, str | None] = (0.0, None)  # (expires_at, model_id)


def _param_count(model_id: str) -> float:
    """Parse parameter count from a model ID like 'qwen3.6-35B-A3B' -> 35.0.
    For MoE ids with multiple numbers (e.g. 35B-A3B), the first B value is
    total params, which matches uoltz's ranking heuristic. Unparseable ids
    rank last (0)."""
    m = _PARAM_COUNT_PATTERN.search(model_id)
    if not m:
        return 0.0
    try:
        return float(m.group(1))
    except ValueError:
        return 0.0


def _base_without_v1(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def _filter_coder(ids: Iterable[str], pattern: re.Pattern[str]) -> list[str]:
    return [i for i in ids if not pattern.search(i)]


def _from_running(base: str, pattern: re.Pattern[str]) -> str | None:
    """Pick largest non-coder model currently loaded and ready."""
    try:
        resp = httpx.get(f"{base}/running", timeout=2.0)
        resp.raise_for_status()
        running = resp.json().get("running", [])
    except Exception as e:
        log.debug("llama-swap /running unreachable: %s", e)
        return None
    ready = [
        entry.get("model")
        for entry in running
        if entry.get("state") == "ready" and entry.get("model")
    ]
    candidates = _filter_coder(ready, pattern)
    if not candidates:
        return None
    return max(candidates, key=_param_count)


def _from_models_list(base: str, pattern: re.Pattern[str]) -> str | None:
    """Nothing loaded - pick largest non-coder from /v1/models. llama-swap
    will load it on demand when the chat request lands."""
    try:
        resp = httpx.get(f"{base}/v1/models", timeout=2.0)
        resp.raise_for_status()
        ids = [m.get("id") for m in resp.json().get("data", []) if m.get("id")]
    except Exception as e:
        log.debug("llama-swap /v1/models unreachable: %s", e)
        return None
    candidates = _filter_coder(ids, pattern)
    if not candidates:
        return None
    return max(candidates, key=_param_count)


def resolve_model(
    *,
    base_url: str | None = None,
    override: str | None = None,
    coder_pattern: str | None = None,
    use_cache: bool = True,
    startup_timeout: float = 0.0,
) -> str:
    """Return the model id to send chat requests to.

    Resolution order:
      1. Explicit `override` argument.
      2. `LLM_MODEL` env var, if set.
      3. Largest ready non-coder model from llama-swap `/running`.
      4. Largest non-coder model from llama-swap `/v1/models`.
      5. `LLM_MODEL_FALLBACK` env var.

    `startup_timeout` enables retry-with-backoff against llama-swap when steps
    3 and 4 both return None (e.g. llama-swap is mid-startup, vLLM cold-starting
    a 35B model can take many minutes). Set this only at process startup; in
    hot paths leave it at 0 so a transient outage doesn't stall a single
    request for minutes.

    Raises RuntimeError if none of the above yield a model id.
    """
    global _cache
    if override:
        return override
    env_pin = os.environ.get("LLM_MODEL")
    if env_pin:
        return env_pin

    base_url = base_url or os.environ.get(
        "LLM_BASE_URL", "http://host.docker.internal:8080/v1"
    )
    base = _base_without_v1(base_url)
    pattern = re.compile(coder_pattern, re.IGNORECASE) if coder_pattern else _DEFAULT_CODER_PATTERN

    if use_cache:
        with _cache_lock:
            expires_at, cached = _cache
            if cached and time.monotonic() < expires_at:
                return cached

    deadline = time.monotonic() + startup_timeout if startup_timeout > 0 else None
    backoff = 1.0
    picked: str | None = None
    while True:
        picked = _from_running(base, pattern) or _from_models_list(base, pattern)
        if picked:
            break
        if deadline is None or time.monotonic() >= deadline:
            break
        log.info(
            "llama-swap not yet ready at %s, retrying in %.1fs (deadline %.0fs away)",
            base, backoff, deadline - time.monotonic(),
        )
        time.sleep(backoff)
        backoff = min(backoff * 2.0, 15.0)

    if not picked:
        picked = os.environ.get("LLM_MODEL_FALLBACK")
    if not picked:
        raise RuntimeError(
            "Could not resolve an LLM model: llama-swap unreachable and no "
            "LLM_MODEL / LLM_MODEL_FALLBACK env var set."
        )

    if use_cache:
        with _cache_lock:
            _cache = (time.monotonic() + _CACHE_TTL_SECONDS, picked)

    log.info("Resolved LLM model: %s", picked)
    return picked


def invalidate_cache() -> None:
    """Force the next resolve_model() call to re-query llama-swap."""
    global _cache
    with _cache_lock:
        _cache = (0.0, None)
