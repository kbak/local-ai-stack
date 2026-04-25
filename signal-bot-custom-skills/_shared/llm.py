"""Thin wrapper around the bot's local LLM for chat-completions calls."""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _resolve_model(base_url: str, fallback: str) -> str:
    """Pick the largest currently-loaded non-coder model via stack_shared.

    Mirrors how every other watcher in the stack picks a model — uoltz's
    hardcoded `config.llm.model_id` is often a stale name (no entry in
    llama-swap), so calling it directly produces 400s like
    'could not find suitable inference handler for ...'.
    """
    try:
        from stack_shared.llm_model import resolve_model
        return resolve_model(base_url=base_url) or fallback
    except Exception as e:
        logger.warning("model resolution failed (%s); using config fallback %r", e, fallback)
        return fallback


def chat(
    system: str,
    user: str,
    *,
    max_tokens: int = 128,
    temperature: float = 0.0,
) -> Optional[str]:
    """One-shot chat completion using the bot's `config.llm` settings.

    Disables Qwen3.x reasoning (`enable_thinking=False`) and strips any
    leaked `<think>...</think>` blocks — without this, short-answer prompts
    (e.g. naming with max_tokens=24) get the entire budget consumed by the
    reasoning trace and return empty content. Every other LLM caller in the
    stack follows the same pattern.

    Returns the assistant text, or None on failure (caller decides fallback).
    """
    try:
        import config  # provided by the signal-bot runtime
        from openai import OpenAI

        model = _resolve_model(config.llm.base_url, config.llm.model_id)
        client = OpenAI(base_url=config.llm.base_url, api_key=config.llm.api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        raw = resp.choices[0].message.content or ""
        return _THINK_RE.sub("", raw).strip()
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return None
