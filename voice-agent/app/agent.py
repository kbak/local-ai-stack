"""Strands agent with skills loaded from the mounted skills directory."""

import logging

from stack_shared.llm_client import env_api_key, env_base_url
from stack_shared.llm_model import invalidate_cache, resolve_model
from strands import Agent
from strands.models.openai import OpenAIModel

from . import config
from .skills_loader import discover

logger = logging.getLogger(__name__)

_agent: Agent | None = None
_tools: list = []
_skill_names: list[str] = []


def build() -> Agent:
    global _agent, _tools, _skill_names
    if _agent is not None:
        return _agent

    _tools, _skill_names = discover(config.SKILLS_DIR)
    logger.info("Discovered %d skills, %d tools", len(_skill_names), len(_tools))

    model = OpenAIModel(
        client_args={"base_url": env_base_url(), "api_key": env_api_key()},
        model_id=resolve_model(),
        params={
            "temperature": config.LLM_TEMPERATURE,
            "max_tokens": config.LLM_MAX_TOKENS,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        },
    )

    _agent = Agent(model=model, tools=_tools, system_prompt=config.VOICE_SYSTEM_PROMPT)
    return _agent


def reset_conversation() -> None:
    """Clear conversation history AND force a re-resolve of the active model
    on the next build. This way a session reset picks up whatever's currently
    loaded in llama-swap - e.g. after the user swaps models via the UI."""
    global _agent
    invalidate_cache()
    _agent = None
