FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app


# Clone uoltz and install dependencies
RUN git clone https://github.com/maciejjedrzejczyk/uoltz.git /uoltz
RUN pip install --no-cache-dir -r /uoltz/app/requirements.txt

# Copy uoltz app as base
RUN cp -r /uoltz/app/. .

# Disable built-in web_search skill (replaced by SearXNG custom skill)
RUN sed -i 's/^enabled: true/enabled: false/' /app/skills/web_search/skill.yaml

# Remove skill attribution messages (don't show which tools were used)
RUN sed -i '/# Show which skills were invoked/{N;N;N;d}' /app/bot.py

# Replace REST API receive with direct signal-cli call to avoid lock contention
RUN python3 - << 'PYEOF'
import re as _re
with open("/app/signal_client.py") as f:
    src = f.read()

new_receive = '''    def receive(self) -> list[dict]:
        """Poll for new incoming messages via the REST API."""
        try:
            resp = self._http.get(f"/v1/receive/{self.number}?timeout=1")
            if resp.status_code == 200:
                return resp.json() or []
            return []
        except Exception as exc:
            logger.error("receive failed: %s", exc)
            return []'''

# Replace the receive method body using regex (avoids unicode dash issues)
patched = _re.sub(
    r'(    def receive\(self\) -> list\[dict\]:.*?return result)',
    new_receive,
    src,
    flags=_re.DOTALL
)
if patched == src:
    raise RuntimeError("receive patch did not match - check signal_client.py source")
with open("/app/signal_client.py", "w") as f:
    f.write(patched)
print("Patched signal_client.py")
PYEOF

# Set poll interval to match receive timeout
RUN sed -i 's/^POLL_INTERVAL = 2/POLL_INTERVAL = 1/' /app/bot.py

# Fix group mention detection: Signal sends @mentions as U+FFFC, not as text prefix
# Also pass mentions through parse_messages and check them in group filter
RUN python3 - << 'PYEOF'
import re as _re

with open("/app/bot.py") as f:
    src = f.read()

# 0. Add import re if not present
if 'import re\n' not in src:
    src = src.replace('import queue\n', 'import queue\nimport re\n', 1)

# 1. Pass mentions through parse_messages
src = src.replace(
    '        if sender and (text or attachments):\n            messages.append({\n                "sender": sender,\n                "text": text,\n                "attachments": attachments,\n                "group_id": group_id,\n            })',
    '        mentions = data.get("mentions", []) or []\n        if sender and (text or attachments):\n            messages.append({\n                "sender": sender,\n                "text": text,\n                "attachments": attachments,\n                "group_id": group_id,\n                "mentions": mentions,\n            })'
)

# 2. Check mentions in group filter (bot's own number in mentions = was @mentioned)
src = src.replace(
    '                if group_id:\n                    prefix = config.signal.group_prefix.lower()\n                    text_lower = text.strip().lower()\n                    if text_lower.startswith(prefix):\n                        # Strip the prefix and process the rest\n                        text = text.strip()[len(prefix):].strip()\n                        logger.info("Group %s, from %s (prefix matched): %s", group_id, sender, text[:80])',
    '                if group_id:\n                    prefix = config.signal.group_prefix.lower()\n                    text_lower = text.strip().lower()\n                    bot_number = config.signal.number\n                    mentions = msg.get("mentions", [])\n                    bot_mentioned = any(m.get("number") == bot_number or m.get("uuid") == bot_number for m in mentions)\n                    if text_lower.startswith(prefix):\n                        # Strip the prefix and process the rest\n                        text = text.strip()[len(prefix):].strip()\n                        logger.info("Group %s, from %s (prefix matched): %s", group_id, sender, text[:80])\n                    elif bot_mentioned:\n                        # Strip leading U+FFFC mention character and whitespace\n                        text = re.sub(r"^[\\uFFFC\\s]+", "", text).strip()\n                        logger.info("Group %s, from %s (mention matched): %s", group_id, sender, text[:80])'
)

with open("/app/bot.py", "w") as f:
    f.write(src)

print("Patched bot.py successfully")
PYEOF

# Fix group send: received groupId is internal_id; /v2/send needs group.XXX= format
# Patch send() to resolve internal group IDs to their group.XXX= form
RUN python3 - << 'PYEOF'
import re as _re
with open("/app/signal_client.py") as f:
    src = f.read()

# Add _resolve_group_id helper and patch send() to use it
helper = '''
    def _resolve_group_id(self, group_id: str) -> str:
        """Convert an internal group ID to the group.XXX= form needed by /v2/send."""
        if group_id.startswith("group."):
            return group_id
        try:
            resp = self._http.get(f"/v1/groups/{self.number}")
            resp.raise_for_status()
            for g in resp.json():
                if g.get("internal_id") == group_id:
                    return g["id"]
        except Exception:
            pass
        return group_id

'''

# Insert helper before the send method
patched = _re.sub(
    r'(\n    def send\(self,)',
    helper + r'\n    def send(self,',
    src,
    count=1
)

# Patch send() to resolve the recipient if it looks like a group internal ID
patched = patched.replace(
    '"recipients": [recipient],',
    '"recipients": [self._resolve_group_id(recipient)],',
    1
)

if patched == src:
    raise RuntimeError("group send patch did not match")
with open("/app/signal_client.py", "w") as f:
    f.write(patched)
print("Patched signal_client.py group send")
PYEOF

# Add react() method to SignalClient and replace ACK message with robot emoji reaction
RUN python3 - << 'PYEOF'
import re as _re

# 1. Add react() to signal_client.py
with open("/app/signal_client.py") as f:
    src = f.read()

react_method = '''
    def react(self, recipient: str, target_author: str, timestamp: int, emoji: str = "🤖") -> bool:
        """Send an emoji reaction to a specific message."""
        try:
            resp = self._http.post(
                f"/v1/reactions/{self.number}",
                json={
                    "reaction": emoji,
                    "recipient": self._resolve_group_id(recipient),
                    "target_author": target_author,
                    "timestamp": timestamp,
                },
            )
            return resp.status_code in (200, 204)
        except Exception as exc:
            logger.error("React failed: %s", exc)
            return False

'''

patched = _re.sub(
    r'(\n    def send\(self,)',
    react_method + r'\n    def send(self,',
    src,
    count=1,
)
if patched == src:
    raise RuntimeError("react() insertion did not match")
with open("/app/signal_client.py", "w") as f:
    f.write(patched)
print("Added react() to signal_client.py")

# 2. Pass timestamp through parse_messages in bot.py
with open("/app/bot.py") as f:
    src = f.read()

# Extract timestamp from envelope and include in message dict
src = src.replace(
    '        mentions = data.get("mentions", []) or []\n        if sender and (text or attachments):\n            messages.append({\n                "sender": sender,\n                "text": text,\n                "attachments": attachments,\n                "group_id": group_id,\n                "mentions": mentions,\n            })',
    '        mentions = data.get("mentions", []) or []\n        timestamp = envelope.get("timestamp") or data.get("timestamp")\n        if sender and (text or attachments):\n            messages.append({\n                "sender": sender,\n                "text": text,\n                "attachments": attachments,\n                "group_id": group_id,\n                "mentions": mentions,\n                "timestamp": timestamp,\n            })',
)

# 3. Replace ACK send in handle_direct_skill with react()
src = src.replace(
    '    # Ack instantly, queue the work\n    signal.send(sender, ACK_MESSAGE)\n    _work_queue.put(("direct_skill", signal, sender, command, dc, args.strip()))',
    '    # Ack instantly, queue the work\n    _work_queue.put(("direct_skill", signal, sender, command, dc, args.strip()))',
)

# 4. Replace ACK send in main loop with react(), passing sender and timestamp
src = src.replace(
    '                # Agent messages — ack instantly, queue for sequential processing\n                signal.send(reply_to, ACK_MESSAGE)\n                _work_queue.put(("agent", signal, reply_to, text))',
    '                # Ack with robot emoji reaction, queue for sequential processing\n                signal.react(reply_to, msg["sender"], msg["timestamp"])\n                _work_queue.put(("agent", signal, reply_to, text))',
)

with open("/app/bot.py", "w") as f:
    f.write(src)
print("Patched bot.py for react() ack")
PYEOF

# Per-sender agent isolation + language instruction
RUN python3 - << 'PYEOF'
with open("/app/agent.py") as f:
    src = f.read()

# 1. Add language instruction to system prompt
src = src.replace(
    'Always be direct and helpful. If you\'re unsure, say so.\n"""',
    'Always be direct and helpful. If you\'re unsure, say so.\n\nAlways respond in the same language the user is currently writing in.\n"""',
)

# 2. Replace single _agent global with per-sender dict
src = src.replace(
    '# Module-level references so we can swap them at runtime\n_agent: Agent | None = None\n_registry: SkillRegistry | None = None',
    '# Module-level references so we can swap them at runtime\n_agents: dict[str, Agent] = {}  # keyed by sender\n_registry: SkillRegistry | None = None\n_model: OpenAIModel | None = None',
)

# 3. Replace create_agent to build shared model/registry, clear per-sender agents
src = src.replace(
    '    global _agent, _registry\n\n    from runtime import state\n\n    mid = model_id or config.llm.model_id\n    max_tok = state.max_tokens or config.llm.max_tokens\n\n    model = OpenAIModel(\n        client_args={\n            "base_url": config.llm.base_url,\n            "api_key": config.llm.api_key,\n        },\n        model_id=mid,\n        params={\n            "temperature": config.llm.temperature,\n            "max_tokens": max_tok,\n        },\n    )\n\n    if _registry is None:\n        _registry = discover_skills()\n\n    system_prompt = _build_system_prompt(_registry)\n\n    _agent = Agent(\n        model=model,\n        tools=_registry.tools,\n        system_prompt=system_prompt,\n    )\n\n    return _agent, _registry',
    '    global _agents, _registry, _model\n\n    from runtime import state\n\n    mid = model_id or config.llm.model_id\n    max_tok = state.max_tokens or config.llm.max_tokens\n\n    _model = OpenAIModel(\n        client_args={\n            "base_url": config.llm.base_url,\n            "api_key": config.llm.api_key,\n        },\n        model_id=mid,\n        params={\n            "temperature": config.llm.temperature,\n            "max_tokens": max_tok,\n        },\n    )\n\n    if _registry is None:\n        _registry = discover_skills()\n\n    # Clear all per-sender agents so they get lazily recreated with new model\n    _agents.clear()\n\n    # Return a sentinel agent for callers that expect one (e.g. scheduler)\n    sentinel = Agent(\n        model=_model,\n        tools=_registry.tools,\n        system_prompt=_build_system_prompt(_registry),\n    )\n    return sentinel, _registry',
)

# 4. Add get_agent_for(sender) and update get_agent() to return sentinel
src = src.replace(
    'def get_agent() -> Agent:\n    """Return the current agent instance."""\n    if _agent is None:\n        raise RuntimeError("Agent not initialized. Call create_agent() first.")\n    return _agent',
    'def get_agent_for(sender: str) -> Agent:\n    """Return (or lazily create) a per-sender Agent instance."""\n    if _model is None or _registry is None:\n        raise RuntimeError("Agent not initialized. Call create_agent() first.")\n    if sender not in _agents:\n        _agents[sender] = Agent(\n            model=_model,\n            tools=_registry.tools,\n            system_prompt=_build_system_prompt(_registry),\n        )\n        logger.info("Created new agent for sender %s", sender)\n    return _agents[sender]\n\n\ndef get_agent() -> Agent:\n    """Return a shared agent instance (used by scheduler and legacy callers)."""\n    if _model is None or _registry is None:\n        raise RuntimeError("Agent not initialized. Call create_agent() first.")\n    # Return any existing agent or create a generic one\n    if _agents:\n        return next(iter(_agents.values()))\n    return Agent(\n        model=_model,\n        tools=_registry.tools,\n        system_prompt=_build_system_prompt(_registry),\n    )',
)

# 5. Update refresh_system_prompt to update all per-sender agents
src = src.replace(
    'def refresh_system_prompt():\n    """Update the agent\'s system prompt (e.g. after toggling markdown)."""\n    if _agent is not None and _registry is not None:\n        _agent.system_prompt = _build_system_prompt(_registry)',
    'def refresh_system_prompt():\n    """Update the system prompt for all active per-sender agents."""\n    if _registry is not None:\n        prompt = _build_system_prompt(_registry)\n        for agent in _agents.values():\n            agent.system_prompt = prompt',
)

with open("/app/agent.py", "w") as f:
    f.write(src)
print("Patched agent.py for per-sender isolation and language instruction")
PYEOF

# Patch bot.py to use get_agent_for(sender) instead of get_agent()
RUN python3 - << 'PYEOF'
with open("/app/bot.py") as f:
    src = f.read()

src = src.replace(
    'from agent import (\n    create_agent, get_agent, get_registry, refresh_system_prompt,',
    'from agent import (\n    create_agent, get_agent, get_agent_for, get_registry, refresh_system_prompt,',
)

src = src.replace(
    '                _, _signal, sender, text = item\n                try:\n                    agent = get_agent()\n                    result = agent(text)',
    '                _, _signal, sender, text = item\n                try:\n                    agent = get_agent_for(sender)\n                    result = agent(text)',
)

with open("/app/bot.py", "w") as f:
    f.write(src)
print("Patched bot.py to use get_agent_for(sender)")
PYEOF

# Add per-group recent-message buffer so the bot has context for ambiguous references
# e.g. "co o tym myslisz" after humans switched topics — the bot now sees recent chat
RUN python3 - << 'PYEOF'
import re as _re

with open("/app/bot.py") as f:
    src = f.read()

# 1. Add a per-group message buffer (deque) near the top of bot.py, after imports
if 'from collections import deque' not in src:
    src = src.replace('import queue\n', 'import queue\nfrom collections import deque\n', 1)

# 2. Insert the buffer dict after the work queue declaration
src = src.replace(
    '_work_queue: queue.Queue = queue.Queue()',
    '_work_queue: queue.Queue = queue.Queue()\n_group_history: dict[str, deque] = {}  # group_id -> recent (sender, text) pairs\n_GROUP_HISTORY_MAX = 10',
)

# 3. In the main message loop, record every group message into the buffer BEFORE
#    deciding whether to invoke the bot.  We target the line that strips the prefix/mention
#    and builds the work queue item.  The pattern we latch onto is the group_id check block.
#    We insert the buffering call just after we have sender, text, group_id available
#    (i.e. right before the prefix/mention check inside the group_id branch).
src = src.replace(
    '                if group_id:\n                    prefix = config.signal.group_prefix.lower()\n                    text_lower = text.strip().lower()\n                    bot_number = config.signal.number\n                    mentions = msg.get("mentions", [])\n                    bot_mentioned = any(m.get("number") == bot_number or m.get("uuid") == bot_number for m in mentions)',
    '                if group_id:\n                    # Buffer this message for context (regardless of bot involvement)\n                    if group_id not in _group_history:\n                        _group_history[group_id] = deque(maxlen=_GROUP_HISTORY_MAX)\n                    _group_history[group_id].append((sender, text.strip()))\n                    prefix = config.signal.group_prefix.lower()\n                    text_lower = text.strip().lower()\n                    bot_number = config.signal.number\n                    mentions = msg.get("mentions", [])\n                    bot_mentioned = any(m.get("number") == bot_number or m.get("uuid") == bot_number for m in mentions)',
)

# 4. When the bot IS invoked in a group, prepend recent chat history to the text
#    so the model knows what "this" refers to.  We patch the two places where
#    _work_queue.put(("agent", ...)) is called for group messages.
src = src.replace(
    '                signal.react(reply_to, msg["sender"], msg["timestamp"])\n                _work_queue.put(("agent", signal, reply_to, text))',
    '                signal.react(reply_to, msg["sender"], msg["timestamp"])\n                # Prepend recent group chat so the model has topic context\n                recent = list(_group_history.get(group_id, []))\n                if len(recent) > 1:  # more than just the current message\n                    history_lines = "\\n".join(f"{s}: {t}" for s, t in recent[:-1])\n                    text_with_ctx = f"[Recent chat in this group]\\n{history_lines}\\n\\n[User asks] {text}"\n                else:\n                    text_with_ctx = text\n                _work_queue.put(("agent", signal, reply_to, text_with_ctx))',
)

with open("/app/bot.py", "w") as f:
    f.write(src)
print("Patched bot.py: per-group message buffer for topic context")
PYEOF

# Disable Qwen thinking mode via system prompt
RUN sed -i 's|You are a helpful AI assistant|/no_think\nYou are a helpful AI assistant|' /app/agent.py

# Pre-download the whisper model
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"

CMD ["python", "bot.py"]
