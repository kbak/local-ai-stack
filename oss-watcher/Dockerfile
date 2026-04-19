FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# stack_shared is installed editable at /shared so a compose bind-mount of
# ./shared:/shared:ro picks up source changes without rebuilding the image.
COPY shared/ /shared/
COPY oss-watcher/pyproject.toml oss-watcher/uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt && \
    grep -v '^-e ' /tmp/requirements.txt > /tmp/requirements-filtered.txt && \
    pip install --no-cache-dir -r /tmp/requirements-filtered.txt && \
    pip install --no-cache-dir --no-deps -e /shared/

COPY oss-watcher/oss_watcher/ ./oss_watcher/

CMD ["python", "-m", "oss_watcher.main"]
