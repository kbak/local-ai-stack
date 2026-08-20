FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bump UOLTZ_REV (any new value) to force a fresh git clone of kbak/uoltz.
# Otherwise Docker caches the clone layer indefinitely and pushes to the
# fork won't be picked up by `docker compose build`.
ARG UOLTZ_REV=2026-08-20-45d402c
RUN echo "uoltz rev: ${UOLTZ_REV}" && git clone https://github.com/kbak/uoltz.git /uoltz
RUN pip install --no-cache-dir -r /uoltz/app/requirements.txt && \
    pip install --no-cache-dir mutagen==1.48.1 && \
    pip install --no-cache-dir yt-dlp==2026.7.4 && \
    pip install --no-cache-dir lingua-language-detector==2.2.0

# stack_shared (resolve_model, etc.). Installed editable at /shared so the
# compose bind-mount of ./shared:/shared:ro picks up source changes without
# rebuilding the image.
COPY shared/ /shared/
RUN pip install --no-cache-dir --no-deps -e /shared/

RUN cp -r /uoltz/app/. .

# Built-in sub-agent skills (YouTube and webpage summarizers) call
# config.make_model(), which normally passes LLM_MODEL straight through. The
# stack intentionally leaves that variable empty so the resident llama-swap
# chat model is selected dynamically; resolve it here just like the main agent
# does instead of sending an invalid empty `model` key.
RUN sed -i '/from strands.models.openai import OpenAIModel/a\    from stack_shared.llm_model import resolve_model' /app/config.py && \
    sed -i 's/model_id=llm.model_id,/model_id=resolve_model(base_url=llm.base_url),/' /app/config.py

# Strands 1.30 always emits `tools: []` for tool-less sub-agents. vLLM rejects
# that OpenAI-incompatible payload; omit the field when no tools are present.
RUN sed -i '/^        if stream:$/i\        if not request["tools"]:\n            request.pop("tools")\n' \
    /usr/local/lib/python3.12/site-packages/strands/models/openai.py

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

# Attachments without a filename arrive as {"filename": null}, so .get("filename", "")
# returns None (the default only applies to a MISSING key) and .lower() throws,
# crashing the main loop on every photo. Coerce None -> "" before .lower().
RUN sed -i 's|a.get("filename", "").lower()|(a.get("filename") or "").lower()|' /app/bot.py

# The upstream runtime model selector considers every ready llama-swap model.
# During a main-model swap the persistent autocomplete model can briefly be the
# only ready entry, causing the tool-using Signal agent to switch to qwen-coder
# (which intentionally has no automatic tool-call parser) and fail with HTTP
# 400. Rerankers, embedders, and image models are likewise not chat models.
RUN sed -i 's|ids = \[entry.get("model") for entry in running if entry.get("model")\]|ids = [entry.get("model") for entry in running if entry.get("model") and not any(token in entry.get("model").lower() for token in ("coder", "reranker", "embed", "bge-", "flux", "stable-diffusion"))]|' /app/agent.py

CMD ["python", "bot.py"]
