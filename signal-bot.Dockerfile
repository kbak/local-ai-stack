FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bump UOLTZ_REV (any new value) to force a fresh git clone of kbak/uoltz.
# Otherwise Docker caches the clone layer indefinitely and pushes to the
# fork won't be picked up by `docker compose build`.
ARG UOLTZ_REV=2026-05-30-0450
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

# Light thinking for the bot. Qwen3 thinking is re-enabled (enable_thinking=True)
# but kept SHORT via a brief-reasoning directive in the system prompt (next sed),
# so the bot stops hallucinating / contradicting itself WITHOUT the 10k-token,
# 60-80s blowups of full default thinking. Measured against the live 35B-A3B
# endpoint: trivial chat ~1-2s / ~200 tok, a reasoning question ~3s / ~570 tok,
# tool calls unaffected (~80 tok). vLLM's qwen3 reasoning-parser strips the
# <think> block into a separate `reasoning` field, so the trace never leaks into
# the Signal reply.
RUN sed -i 's/"max_tokens": max_tok,/"max_tokens": max_tok,\n            "extra_body": {"chat_template_kwargs": {"enable_thinking": True}},/' /app/agent.py

# Remove the /no_think soft-switch (it would override enable_thinking=True) and
# replace it with a tight thinking budget so reasoning stays brief and fast.
RUN sed -i 's|^/no_think$|Think briefly before replying: a sentence or two to check facts and avoid contradicting yourself, then answer. Skip thinking for greetings and trivial messages. Keep reasoning short to stay fast.|' /app/agent.py

CMD ["python", "bot.py"]
