FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install signal-cli
RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless wget && \
    rm -rf /var/lib/apt/lists/* && \
    wget -q https://github.com/AsamK/signal-cli/releases/download/v0.14.1/signal-cli-0.14.1.tar.gz -O /tmp/signal-cli.tar.gz && \
    tar -xzf /tmp/signal-cli.tar.gz -C /opt && \
    ln -s /opt/signal-cli-0.14.1/bin/signal-cli /usr/local/bin/signal-cli && \
    rm /tmp/signal-cli.tar.gz

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
        """Poll for new incoming messages using signal-cli directly."""
        import subprocess, json as _json
        try:
            result = subprocess.run(
                ["signal-cli", "--config", "/signal-cli-data",
                 "--output", "json", "-a", self.number,
                 "receive", "--timeout", "10"],
                capture_output=True, text=True, timeout=30
            )
            messages = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if line:
                    try:
                        messages.append(_json.loads(line))
                    except Exception:
                        pass
            return messages
        except Exception as exc:
            logger.error("signal-cli receive failed: %s", exc)
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
RUN sed -i 's/^POLL_INTERVAL = 2/POLL_INTERVAL = 12/' /app/bot.py

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

# Disable Qwen thinking mode via system prompt
RUN sed -i 's|You are a helpful AI assistant|/no_think\nYou are a helpful AI assistant|' /app/agent.py

# Pre-download the whisper model
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"

CMD ["python", "bot.py"]
