FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY shared/ /shared/
COPY tg-watcher/pyproject.toml tg-watcher/uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt && \
    grep -v '^-e ' /tmp/requirements.txt > /tmp/requirements-filtered.txt && \
    pip install --no-cache-dir -r /tmp/requirements-filtered.txt && \
    pip install --no-cache-dir --no-deps /shared/

COPY tg-watcher/tg_watcher/ ./tg_watcher/
COPY tg-watcher/auth.py ./auth.py

CMD ["python", "-m", "tg_watcher.main"]
