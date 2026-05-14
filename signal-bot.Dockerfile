FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bump UOLTZ_REV (any new value) to force a fresh git clone of kbak/uoltz.
# Otherwise Docker caches the clone layer indefinitely and pushes to the
# fork won't be picked up by `docker compose build`.
ARG UOLTZ_REV=2026-05-12-1700
RUN echo "uoltz rev: ${UOLTZ_REV}" && git clone https://github.com/kbak/uoltz.git /uoltz
RUN pip install --no-cache-dir -r /uoltz/app/requirements.txt && \
    pip install --no-cache-dir mutagen && \
    pip install --no-cache-dir -U yt-dlp && \
    pip install --no-cache-dir lingua-language-detector

# stack_shared (resolve_model, etc.). Installed editable at /shared so the
# compose bind-mount of ./shared:/shared:ro picks up source changes without
# rebuilding the image.
COPY shared/ /shared/
RUN pip install --no-cache-dir --no-deps -e /shared/

RUN cp -r /uoltz/app/. .

# Make agent timeout configurable via AGENT_TIMEOUT_S env var (default 120s).
# The upstream default of 60s is too short for the 35B model on long contexts.
RUN sed -i 's/^AGENT_TIMEOUT = 60$/AGENT_TIMEOUT = int(os.environ.get("AGENT_TIMEOUT_S", "120"))/' /app/bot.py

# Disable Qwen3 extended thinking for the bot — the jinja template defaults to
# thinking ON, which burns 10k+ tokens per response (60-80s on 35B). LibreChat
# sends its own enable_thinking=true; the bot always wants it off.
RUN sed -i 's/"max_tokens": max_tok,/"max_tokens": max_tok,\n            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},/' /app/agent.py

CMD ["python", "bot.py"]
