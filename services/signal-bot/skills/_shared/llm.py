"""Thin wrapper around the bot's local LLM for chat-completions calls."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _resolve_model(base_url: str, fallback: str) -> str:
    """Prefer the loaded chat model; the bot's configured model may be stale."""
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
    """Use the bot's settings; return None on failure so callers can fall back."""
    try:
        import config  # provided by the signal-bot runtime
        from stack_shared.llm_chat import chat as shared_chat

        model = _resolve_model(config.llm.base_url, config.llm.model_id)
        return shared_chat(
            system, user,
            base_url=config.llm.base_url,
            api_key=config.llm.api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return None
