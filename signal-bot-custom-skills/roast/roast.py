"""Roast battle skill — `/roast` entry point.

Orchestrates: parse input → resolve voices → resolve personas (cached) →
run the agent battle loop → ship transcript text → synthesize per-turn audio
→ stitch → send Signal voice note.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import sys
import tempfile
from contextlib import AsyncExitStack
from pathlib import Path

import httpx
from openai import AsyncOpenAI
from strands import tool

# Sibling skill modules
_SKILL_DIR = str(Path(__file__).parent)
if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)
# Sibling-skill `_shared/` package
_CUSTOM_SKILLS_ROOT = str(Path(__file__).parent.parent)
if _CUSTOM_SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _CUSTOM_SKILLS_ROOT)
# uoltz app for `agent.get_running_model` and `config`
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

import audio as audio_mod  # noqa: E402
import cache as persona_cache  # noqa: E402
import parse as parse_input  # noqa: E402
from agent_loop import connect_mcp, generate_topic, resolve_persona, run_battle  # noqa: E402
from _shared import voice_match  # noqa: E402

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────


def _audio_api_url() -> str:
    return os.getenv("AUDIO_API_URL", "http://audio-api:8088").rstrip("/")


def _list_voices() -> list[str]:
    """Fetch the current list of voice samples from audio-api."""
    resp = httpx.get(f"{_audio_api_url()}/v1/voices/clone", timeout=10)
    resp.raise_for_status()
    return resp.json().get("voices", [])


def _resolve_one_voice(name: str, available: list[str]) -> str | None:
    """Run the same greedy fuzzy match `/tts` uses, against tokens of `name`."""
    voice, _rest = voice_match.match_voice(name.split(), available)
    return voice


def _resolve_model() -> str:
    """Pick the largest currently-loaded *chat* model (filters out coder models).

    Uses the stack-wide `stack_shared.resolve_model()` helper — the same
    "single source of truth" all other watchers use. That helper queries
    llama-swap's /running, filters out coder/autocomplete models by name
    pattern, and picks by parameter count. Final fallback is uoltz's
    `config.llm.model_id`.
    """
    try:
        from stack_shared.llm_model import resolve_model
        import config

        return resolve_model(base_url=config.llm.base_url) or config.llm.model_id
    except Exception:
        logger.exception("model resolution failed; falling back to env LLM_MODEL")
        return os.getenv("LLM_MODEL", "")


def _llm_client() -> AsyncOpenAI:
    """OpenAI async client pointed at the bot's configured LLM endpoint."""
    import config

    return AsyncOpenAI(base_url=config.llm.base_url, api_key=config.llm.api_key)


# ── Async core ───────────────────────────────────────────────────────────


async def _run_async(parsed: parse_input.Parsed, *, react, send_text) -> tuple[list, str, str]:
    """Resolve everything, run the battle, return (transcript, model, topic)."""
    available = _list_voices()
    voice_a = _resolve_one_voice(parsed.person1, available)
    voice_b = _resolve_one_voice(parsed.person2, available)
    if voice_a is None:
        raise ValueError(f"no voice matches '{parsed.person1}'")
    if voice_b is None:
        raise ValueError(f"no voice matches '{parsed.person2}'")
    if voice_a == voice_b:
        raise ValueError(
            f"both names matched the same voice ({voice_a}). "
            "Use distinct samples or full names."
        )

    model = _resolve_model()
    if not model:
        raise RuntimeError("no LLM model resolved (llama-swap unreachable and LLM_MODEL unset)")

    # Title-case the user input for persona prompts. We use the input verbatim
    # (not the voice stem) so a /roast hunter s thompson, ... still feeds a
    # natural name into the persona prompt even if the file is hunter_thompson.
    name_a = parsed.person1.strip().title()
    name_b = parsed.person2.strip().title()

    client = _llm_client()
    async with AsyncExitStack() as stack:
        sessions, tools, tool_to_server = await connect_mcp(stack)
        logger.info("[roast] %d MCP tools available", len(tools))

        # Personas — cached on disk, regenerated on miss.
        needs_persona = any(persona_cache.get(nm) is None for nm in (name_a, name_b))
        if needs_persona:
            react("🎭")
        for nm in (name_a, name_b):
            if persona_cache.get(nm) is None:
                persona = await resolve_persona(client, model, nm, tools, sessions, tool_to_server)
                persona_cache.put(nm, persona)
        persona_a = persona_cache.get(name_a) or f"You are {name_a}."
        persona_b = persona_cache.get(name_b) or f"You are {name_b}."

        # If no topic was supplied, ask the LLM to invent something spicy.
        if parsed.topic:
            topic = parsed.topic
        else:
            react("🔥")
            topic = await generate_topic(client, model, name_a, name_b)
            logger.info("[roast] auto-topic: %s", topic)

        # The one informative status message — useful info worth seeing.
        react("🥊")
        send_text(f"🥊 {parsed.turns} turns · topic: {topic}")

        transcript = await run_battle(
            client=client,
            model=model,
            persona_a=persona_a,
            persona_b=persona_b,
            name_a=name_a,
            name_b=name_b,
            voice_a=voice_a,
            voice_b=voice_b,
            topic=topic,
            turns=parsed.turns,
            tools=tools,
            sessions=sessions,
            tool_to_server=tool_to_server,
            rng=random.Random(),
        )

    return transcript, model, topic


# ── Skill entry point ────────────────────────────────────────────────────


def _format_transcript(transcript: list[tuple[str, str, str]]) -> str:
    """Render the back-and-forth as a readable Signal text message.

    No turn numbers (looks busy on phone screens). Each turn separated by a
    blank line so it's easy to scan."""
    return "\n\n".join(f"{name}: {text}" for name, _voice, text in transcript)


def _detect_language(transcript: list[tuple[str, str, str]], forced: str | None) -> str:
    """Decide what language to pass to audio-api per turn.

    If the user forced a language with the leading lang token, use that for
    every turn. Otherwise auto-detect from the joined transcript via lingua;
    fall back to English if lingua is unavailable.
    """
    if forced:
        return forced
    blob = " ".join(text for _, _, text in transcript)
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / "tts_clone"))
        import lang as lang_mod
        return lang_mod.detect(blob)
    except Exception:
        return "en"


@tool
def roast(
    input: str,
    status_fn=None,
    signal=None,
    sender: str | None = None,
    target_author: str | None = None,
    target_ts: int | None = None,
) -> str:
    """Run a roast battle between two voices and ship a Signal voice note.

    Usage:
        /roast <person1>, <person2>
        /roast <person1>, <person2> <turns>
        /roast <person1>, <person2> <turns> <topic...>
        /roast <lang> <person1>, <person2> [turns] [topic...]

    Voices are resolved against VOICE_SAMPLES_DIR via the same greedy fuzzy
    match used by `/tts` — record samples first with `/sample` if missing.
    """

    # `react` puts an emoji on the user's /roast message — non-spammy progress
    # indicator. Falls back to logging when reaction context is missing
    # (e.g. tool invoked by the agent loop, not a slash command).
    can_react = signal is not None and sender and target_author and target_ts
    def react(emoji: str):
        if can_react:
            try:
                signal.react(sender, target_author, target_ts, emoji)
            except Exception:
                logger.exception("reaction %s failed", emoji)
        else:
            logger.info("[roast] (would react) %s", emoji)

    def send_text(msg: str):
        if signal is not None and sender:
            signal.send(sender, msg)
        else:
            logger.info("[roast] %s", msg)

    # 1. Parse.
    try:
        parsed = parse_input.parse(input)
    except ValueError as e:
        return (
            f"Invalid input: {e}\n"
            "Usage: /roast [lang] <person1>, <person2> [turns] [topic]\n"
            "Example: /roast hillary clinton, donald trump 8 better than you\n"
            "Use `/voices` to list available samples."
        )

    # 2. Run the battle.
    try:
        transcript, model, topic = asyncio.run(_run_async(parsed, react=react, send_text=send_text))
    except ValueError as e:
        return f"❌ {e}"
    except Exception as e:
        logger.exception("roast battle failed")
        return f"❌ Roast failed: {e}"

    if not transcript:
        return "❌ No turns produced (model may be stuck — try a different topic or names)."

    # 3. Ship the transcript first.
    transcript_text = _format_transcript(transcript)
    if signal is not None and sender:
        signal.send(sender, transcript_text)

    # 4. Synthesize per-turn audio. Reaction-only status — no text spam.
    react("🎤")
    language = _detect_language(transcript, parsed.language)

    with tempfile.TemporaryDirectory(prefix="roast_") as tmp:
        tmp_path = Path(tmp)
        wav_paths: list[Path] = []
        for i, (_name, voice, text) in enumerate(transcript, 1):
            wav = tmp_path / f"{i:03d}_{voice}.wav"
            if audio_mod.synthesize_turn(text, voice, language, wav):
                wav_paths.append(wav)

        if not wav_paths:
            return "❌ All TTS calls failed — no audio to ship."

        react("🎬")
        out_ogg = tmp_path / "roast.ogg"
        if not audio_mod.stitch_to_ogg(wav_paths, out_ogg):
            return "❌ Stitch failed — check signal-bot logs."

        ogg_bytes = out_ogg.read_bytes()

        # 5. Send voice note.
        if signal is not None and sender:
            try:
                if not signal.send_voice(sender, ogg_bytes):
                    raise RuntimeError("signal send_voice returned failure")
            except Exception as e:
                logger.exception("voice-note send failed")
                return f"Synthesized {len(ogg_bytes) // 1024} KB but Signal send failed: {e}"
            return ""  # transcript was already sent; bot's empty-reply patch suppresses trailer

    # No Signal client — return transcript only.
    return transcript_text
