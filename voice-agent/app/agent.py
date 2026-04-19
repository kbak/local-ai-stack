"""Strands agent with skills loaded from the mounted skills directory."""

import logging

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
        client_args={"base_url": config.LLM_BASE_URL, "api_key": config.LLM_API_KEY},
        model_id=config.LLM_MODEL,
        params={
            "temperature": config.LLM_TEMPERATURE,
            "max_tokens": config.LLM_MAX_TOKENS,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        },
    )

    _agent = Agent(model=model, tools=_tools, system_prompt=config.VOICE_SYSTEM_PROMPT)
    return _agent


def reset_conversation() -> None:
    """Clear conversation history for a fresh session."""
    global _agent
    if _agent is not None and hasattr(_agent, "messages"):
        _agent.messages = []
