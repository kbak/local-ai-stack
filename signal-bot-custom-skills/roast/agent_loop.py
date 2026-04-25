"""Roast battle agent loop — ported from duel.py with logic preserved.

Includes:
  - `Agent` dataclass (name + system prompt + clean text history)
  - `ThinkFilter` to strip <think>...</think> from streamed output
  - MCP plumbing: connect, expose tools to OpenAI, dispatch tool calls
  - `is_repetitive` — difflib-based loop detection
  - `resolve_persona` — LLM-driven persona generation with tool calls
  - `run_turn` — one streaming turn with tool-call rounds
  - `run_battle` — the full back-and-forth with stall recovery + pivots

The repetition detection, pivot interval, stall-recovery via forced tool calls
and the meta-prompts are all preserved verbatim from duel.py.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from prompts import PERSONA_LOOKUP_PROMPT, SOUL

logger = logging.getLogger(__name__)


# ── MCP servers exposed via mcp-proxy ────────────────────────────────────
# Same set as duel.py; if any are unreachable, _connect_one quietly skips them.
_MCP_PROXY_DEFAULT = "http://mcp-proxy:8083"
_MCP_SERVERS = (
    "searxng",
    "time",
    "fetch",
    "arxiv",
    "youtube",
    "hackernews",
    "weather",
    "github",
)
CONNECT_TIMEOUT = 8.0


def _mcp_url(server: str) -> str:
    import os
    base = os.getenv("MCP_PROXY_URL", _MCP_PROXY_DEFAULT).rstrip("/")
    return f"{base}/servers/{server}/mcp"


# ── Agent state ──────────────────────────────────────────────────────────


@dataclass
class Agent:
    name: str
    model: str
    system_prompt: str
    voice: str | None = None
    history: list = field(default_factory=list)  # clean text only

    def build_messages(self, incoming: str, window: int = 24):
        msgs = [{"role": "system", "content": self.system_prompt}]
        msgs.extend(self.history[-window:])
        msgs.append({"role": "user", "content": incoming})
        return msgs


# ── <think> stripper ─────────────────────────────────────────────────────


class ThinkFilter:
    """Strip <think>...</think> from a streaming text feed."""

    def __init__(self):
        self.buf = ""
        self.cursor = 0
        self.in_think = False

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        out = ""
        while True:
            if self.in_think:
                idx = self.buf.find("</think>", self.cursor)
                if idx == -1:
                    return out
                self.cursor = idx + len("</think>")
                self.in_think = False
            else:
                idx = self.buf.find("<think>", self.cursor)
                if idx == -1:
                    safe = len(self.buf) - 7  # hold back possible partial tag
                    if safe > self.cursor:
                        out += self.buf[self.cursor:safe]
                        self.cursor = safe
                    return out
                out += self.buf[self.cursor:idx]
                self.cursor = idx + len("<think>")
                self.in_think = True

    def flush(self) -> str:
        if self.in_think:
            return ""
        return self.buf[self.cursor:]

    def clean(self) -> str:
        return re.sub(r"<think>.*?</think>", "", self.buf, flags=re.DOTALL).strip()


# ── Repetition detection ─────────────────────────────────────────────────


_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    return " ".join(_WORD_RE.findall(text.lower()))


def is_repetitive(candidate: str, recent: list[str], threshold: float = 0.55) -> bool:
    """True if candidate looks too similar to any recent message."""
    cand = _normalize(candidate)
    if len(cand) < 40:
        return False
    for prev in recent:
        p = _normalize(prev)
        if not p:
            continue
        ratio = difflib.SequenceMatcher(None, cand, p, autojunk=False).ratio()
        if ratio >= threshold:
            return True
    return False


# ── MCP wiring ───────────────────────────────────────────────────────────


def _mcp_tools_to_openai(server: str, tools) -> list:
    out = []
    for t in tools:
        name = f"{server}__{t.name}"[:64]
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": (t.description or "")[:1024],
                "parameters": t.inputSchema or {"type": "object", "properties": {}},
            },
        })
    return out


async def _connect_one(name: str, url: str):
    """Open one MCP connection in its own sub-stack. Returns (name, session, tools, sub) or (name, None, None, None)."""
    sub = AsyncExitStack()
    try:
        await sub.__aenter__()
        async with asyncio.timeout(CONNECT_TIMEOUT):
            read, write, _ = await sub.enter_async_context(streamablehttp_client(url))
            session = await sub.enter_async_context(ClientSession(read, write))
            await session.initialize()
            resp = await session.list_tools()
        return name, session, resp.tools, sub
    except BaseException as e:
        try:
            await sub.aclose()
        except BaseException:
            pass
        msg = str(e) or type(e).__name__
        logger.warning("[mcp] %s: FAILED (%s)", name, msg)
        return name, None, None, None


async def connect_mcp(stack: AsyncExitStack):
    """Connect to all MCP servers and return (sessions, openai_tools, tool_to_server)."""
    sessions: dict = {}
    all_tools: list = []
    tool_to_server: dict = {}
    for name in _MCP_SERVERS:
        n, session, tools, sub = await _connect_one(name, _mcp_url(name))
        if session is None:
            continue
        stack.push_async_callback(sub.aclose)
        sessions[n] = session
        all_tools.extend(_mcp_tools_to_openai(n, tools))
        for t in tools:
            tool_to_server[f"{n}__{t.name}"[:64]] = (n, t.name)
        logger.info("[mcp] %s: %d tools", n, len(tools))
    return sessions, all_tools, tool_to_server


async def _call_tool(sessions, tool_to_server, prefixed: str, args: dict) -> str:
    if prefixed not in tool_to_server:
        return f"error: unknown tool {prefixed}"
    server, orig = tool_to_server[prefixed]
    try:
        result = await sessions[server].call_tool(orig, args)
        parts = [c.text for c in result.content if hasattr(c, "text")]
        return "\n".join(parts) or "(empty)"
    except Exception as e:
        return f"error: {e}"


# ── Topic generation ─────────────────────────────────────────────────────


_TOPIC_PROMPT = """Two people are about to enter a roast battle. Invent a sharp, specific opening topic for them — something with built-in tension. One sentence, max 12 words. No preamble, no explanation, just the topic.

Examples (study the shape, don't reuse):
- whose career is more of a fucking museum exhibit
- who's a worse role model for their own children
- whose autobiography would be funnier as fiction
- who got humiliated harder by their own ambition

Combatants: {a} vs {b}.

Output only the topic line. No quotes, no markdown."""


async def generate_topic(client, model: str, name_a: str, name_b: str) -> str:
    """Ask the LLM to invent a sharp topic for the two named combatants."""
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _TOPIC_PROMPT.format(a=name_a, b=name_b)}],
            stream=False,
            temperature=1.1,
            max_tokens=64,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        raw = (resp.choices[0].message.content or "").strip()
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        # Take first line, trim quotes/punctuation/markdown.
        first_line = cleaned.splitlines()[0] if cleaned else ""
        first_line = first_line.strip().strip("\"'`*-").strip()
        if first_line:
            return first_line
    except Exception:
        logger.exception("topic generation failed")
    return f"who's the bigger disaster, {name_a} or {name_b}"


# ── Persona resolution ───────────────────────────────────────────────────


async def resolve_persona(client, model: str, name: str, tools, sessions, tool_to_server) -> str:
    """Ask the big model for a short persona blurb. Lets it use search/fetch if needed."""
    logger.info("[roast] resolving persona: %s ...", name)
    scratch = [{"role": "user", "content": PERSONA_LOOKUP_PROMPT.format(name=name)}]

    for _ in range(4):  # tool rounds cap
        pending_tc = {}
        resp = await client.chat.completions.create(
            model=model,
            messages=scratch,
            tools=tools or None,
            stream=False,
            temperature=0.6,
            max_tokens=1024,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        msg = resp.choices[0].message
        content_accum = msg.content or ""
        if msg.tool_calls:
            for tc in msg.tool_calls:
                pending_tc[tc.id] = {
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": tc.function.arguments or "{}",
                }

        if pending_tc:
            scratch.append({
                "role": "assistant",
                "content": content_accum or None,
                "tool_calls": [
                    {"id": s["id"], "type": "function", "function": {"name": s["name"], "arguments": s["args"]}}
                    for s in pending_tc.values()
                ],
            })
            for s in pending_tc.values():
                try:
                    args = json.loads(s["args"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await _call_tool(sessions, tool_to_server, s["name"], args)
                scratch.append({"role": "tool", "tool_call_id": s["id"], "content": result[:4000]})
            continue

        blurb = re.sub(r"<think>.*?</think>", "", content_accum, flags=re.DOTALL).strip()
        if blurb:
            return blurb
        break

    # Fallback if the model refuses or stalls.
    return f"You are {name}. Stay in character as them — their voice, values, and quirks."


# ── One turn ─────────────────────────────────────────────────────────────


async def run_turn(
    client,
    agent: Agent,
    incoming: str,
    tools,
    sessions,
    tool_to_server,
    *,
    force_tool: bool = False,
) -> str:
    scratch = agent.build_messages(incoming)
    final_text = ""

    for round_i in range(8):  # tool-call rounds safety cap
        filt = ThinkFilter()
        pending_tc = {}
        content_accum = ""

        # Only force on the first round — after the tool result comes back, let the model free-form.
        tool_choice = "required" if (force_tool and round_i == 0 and tools) else "auto"
        stream = await client.chat.completions.create(
            model=agent.model,
            messages=scratch,
            tools=tools or None,
            tool_choice=tool_choice if tools else None,
            stream=True,
            temperature=1.15 if force_tool else 1.05,
            max_tokens=80,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content_accum += delta.content
                filt.feed(delta.content)  # feed but discard streaming output (no live display in Signal)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    i = tc.index
                    slot = pending_tc.setdefault(i, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments

        if pending_tc:
            tc_list = []
            for i in sorted(pending_tc):
                s = pending_tc[i]
                tc_list.append({
                    "id": s["id"] or f"call_{i}",
                    "type": "function",
                    "function": {"name": s["name"], "arguments": s["args"] or "{}"},
                })
            scratch.append({"role": "assistant", "content": content_accum or None, "tool_calls": tc_list})
            for tc in tc_list:
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await _call_tool(sessions, tool_to_server, tc["function"]["name"], args)
                scratch.append({"role": "tool", "tool_call_id": tc["id"], "content": result[:8000]})
            continue

        final_text = filt.clean()
        break

    if final_text.strip():
        agent.history.append({"role": "user", "content": incoming})
        agent.history.append({"role": "assistant", "content": final_text})
    return final_text


# ── Full battle ──────────────────────────────────────────────────────────


# Pivot every N successful turns. Same constant as duel.py.
PIVOT_EVERY = 5
# Stop after this many consecutive empty turns.
MAX_STALL_STREAK = 3


async def run_battle(
    *,
    client,
    model: str,
    persona_a: str,
    persona_b: str,
    name_a: str,
    name_b: str,
    voice_a: str,
    voice_b: str,
    topic: str,
    turns: int,
    tools,
    sessions,
    tool_to_server,
    rng,
) -> list[tuple[str, str, str]]:
    """Run the back-and-forth. Returns [(speaker_name, voice, text), ...].

    All the duel.py mechanics are preserved:
      - random opening agent
      - opening meta-prompt embedding the topic
      - repetition detection -> forced pivot meta-prompt
      - PIVOT_EVERY interval -> nudge to switch angles
      - stall recovery -> force a tool call
    """
    agent_a = Agent(name_a, model, SOUL.format(name=name_a, persona=persona_a, other=name_b), voice=voice_a)
    agent_b = Agent(name_b, model, SOUL.format(name=name_b, persona=persona_b, other=name_a), voice=voice_b)

    # Random opening agent (preserves duel.py behaviour).
    pair = [agent_a, agent_b]
    rng.shuffle(pair)
    first, second = pair

    incoming = (
        f"(meta: this is the opening line of the roast battle. Topic/angle: \"{topic}\". "
        f"Open with a roast aimed at {second.name} that uses this topic as the setup or punch. "
        f"One line. No preamble, no \"alright let's go\", no announcing yourself — just the roast.)"
    )
    speaker, listener = first, second
    turns_done = 0
    recent_turns: list[str] = []
    force_tool = False
    stall_streak = 0
    turns_since_pivot = 0

    transcript: list[tuple[str, str, str]] = []  # (speaker_name, voice, text)

    while turns_done < turns:
        text = await run_turn(
            client, speaker, incoming, tools, sessions, tool_to_server,
            force_tool=force_tool,
        )
        turns_done += 1

        if text.strip() and speaker.voice:
            transcript.append((speaker.name, speaker.voice, text))

        stalled = not text.strip()
        looped = (not stalled) and is_repetitive(text, recent_turns)

        if stalled:
            stall_streak += 1
            if stall_streak >= MAX_STALL_STREAK:
                logger.warning("[roast] both agents stalled %dx — stopping early.", stall_streak)
                break
            logger.info("[roast] %s stalled — nudging %s with forced tool.", speaker.name, listener.name)
            incoming = (
                "(meta: your last turn went silent. "
                "Pick a tool, call it, and react to what comes back.)"
            )
            force_tool = True
        elif looped:
            stall_streak = 0
            turns_since_pivot = 0
            logger.info("[roast] loop detected — forcing %s to pivot.", listener.name)
            incoming = (
                "(meta: you two are camping on the same joke. Drop it. "
                "Pick a FRESH angle from your Ammo list — one you haven't touched — "
                "and hit that instead. Do not mention the previous topic.)"
            )
            force_tool = False
            recent_turns.clear()
        elif turns_since_pivot >= PIVOT_EVERY:
            stall_streak = 0
            turns_since_pivot = 0
            logger.info("[roast] pivot interval — nudging %s to switch angles.", listener.name)
            incoming = (
                "(meta: time to pivot. Grab a different item from your Ammo list — "
                "something unrelated to the last few exchanges. Fresh target, one line.)\n\n"
                + text
            )
            force_tool = False
            recent_turns.clear()
        else:
            stall_streak = 0
            turns_since_pivot += 1
            recent_turns.append(text)
            if len(recent_turns) > 6:
                recent_turns.pop(0)
            incoming = text
            force_tool = False

        speaker, listener = listener, speaker

    return transcript
