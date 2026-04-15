FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install all dependencies from the lockfile (includes shared's transitive deps)
COPY shared/ /shared/
COPY calendar-watcher/pyproject.toml calendar-watcher/uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt && \
    grep -v '^-e ' /tmp/requirements.txt > /tmp/requirements-filtered.txt && \
    pip install --no-cache-dir -r /tmp/requirements-filtered.txt && \
    pip install --no-cache-dir --no-deps /shared/

COPY calendar-watcher/calendar_watcher/ ./calendar_watcher/

RUN mkdir -p /data

CMD ["python", "-m", "calendar_watcher.main"]
