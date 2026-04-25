"""Thin wrapper around the bot's local LLM for chat-completions calls."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def chat(
    system: str,
    user: str,
    *,
    max_tokens: int = 64,
    temperature: float = 0.0,
) -> Optional[str]:
    """One-shot chat completion using the bot's `config.llm` settings.

    Returns the assistant text, or None on failure (caller decides fallback).
    """
    try:
        import config  # provided by the signal-bot runtime
        from openai import OpenAI

        client = OpenAI(base_url=config.llm.base_url, api_key=config.llm.api_key)
        resp = client.chat.completions.create(
            model=config.llm.model_id,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return None
