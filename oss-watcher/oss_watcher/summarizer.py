"""Fetch last 7 days of activity, summarize via LLM, send via Signal."""

from __future__ import annotations

import logging

from stack_shared.llm_chat import chat

from .config import (
    GITHUB_REPO,
    DISCORD_CHANNEL_ID,
    INFERENCE_API_KEY,
    INFERENCE_BASE_URL,
    INFERENCE_MODEL,
)
from .discord_client import fetch_messages, format_transcript as discord_transcript
from .github_client import fetch_activity, format_transcript as github_transcript
from .signal_client import send_message

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a concise open-source project analyst. The user will give you a week's worth of \
activity from a Discord channel and a GitHub repository. Produce a clear weekly brief in \
plain text covering:
- Merged PRs and what they changed
- Notable open PRs under active discussion
- New or resolved issues worth knowing about
- Key themes or debates from Discord
- Anything that looks like a blocker or a significant decision being made
Skip noise, one-word replies, and bot messages. Be concise but capture anything a \
contributor or maintainer would find valuable.\
"""


def run_summary() -> None:
    log.info("Starting weekly OSS summary...")

    discord_msgs = fetch_messages(days=7)
    gh_activity = fetch_activity(days=7)

    discord_text = discord_transcript(discord_msgs)
    github_text = github_transcript(gh_activity)

    if not discord_text and not github_text:
        log.info("No activity this week — skipping brief")
        return

    user_prompt = (
        f"Here is the last 7 days of activity for the project.\n\n"
        f"### Discord channel ({DISCORD_CHANNEL_ID})\n\n"
        f"{discord_text or '(no messages)'}\n\n"
        f"### GitHub repository ({GITHUB_REPO})\n\n"
        f"{github_text or '(no activity)'}"
    )

    log.info(
        "Summarising %d Discord messages and %d GitHub items via LLM...",
        len(discord_msgs),
        len(gh_activity["issues"]) + len(gh_activity["prs"]),
    )

    summary = chat(
        _SYSTEM_PROMPT,
        user_prompt,
        base_url=INFERENCE_BASE_URL,
        api_key=INFERENCE_API_KEY,
        model=INFERENCE_MODEL,
    )

    send_message(f"*OSS weekly brief*\n\n{summary}")
    log.info("Brief sent.")
