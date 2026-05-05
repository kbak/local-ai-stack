"""Thin wrapper for a single-turn LLM chat completion."""

from __future__ import annotations

import re

from .llm_client import get_client
from .llm_model import resolve_model

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def chat(
    system: str,
    user: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.3,
) -> str:
    """Send a single system+user turn and return the assistant's reply.

    All kwargs are optional. Unset ones are resolved from env / llama-swap:
      - base_url / api_key -> `LLM_BASE_URL` / `LLM_API_KEY` env, then defaults
      - model -> resolve_model() picks the largest non-coder model currently
        loaded in llama-swap.

    Thinking mode is disabled for all calls — Qwen3's reasoning trace consumes
    the token budget and returns empty content when thinking is left on.
    Any leaked <think>...</think> blocks are stripped as a safety net.
    """
    client = get_client(base_url=base_url, api_key=api_key)
    mid = model or resolve_model(base_url=base_url)
    response = client.chat.completions.create(
        model=mid,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    raw = response.choices[0].message.content or ""
    return _THINK_RE.sub("", raw).strip()
