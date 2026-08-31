"""Persist deterministic direct-skill outcomes in conversational history."""

import logging

logger = logging.getLogger(__name__)


def record_direct_skill(agent, command: str, args: str, result: str | None) -> None:
    """Add a compact operation record so later follow-ups have factual context."""
    if not hasattr(agent, "messages"):
        return

    invocation = command + (f" {args}" if args else "")
    outcome = result or "Completed successfully without a text result."
    record = (
        "<completed_operation>\n"
        f"Invocation: {invocation}\n"
        f"Result: {outcome}\n"
        "This is an authoritative result from a completed direct skill.\n"
        "</completed_operation>"
    )
    try:
        agent.messages.extend([
            {"role": "user", "content": [{"text": invocation}]},
            {"role": "assistant", "content": [{"text": record}]},
        ])
        logger.info("Recorded direct skill %s in conversation history", command)
    except Exception:
        # History enrichment must never turn a completed skill into a failure.
        logger.exception("Could not record direct skill %s in history", command)
