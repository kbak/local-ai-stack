FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install shared library
COPY shared/ /shared/
RUN pip install --no-cache-dir /shared/

# Install locked dependencies
# Exclude the local stack-shared path dep (already installed above)
COPY meal-watcher/pyproject.toml meal-watcher/uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt && \
    grep -v '^-e ' /tmp/requirements.txt > /tmp/requirements-filtered.txt && \
    pip install --no-cache-dir -r /tmp/requirements-filtered.txt

COPY meal-watcher/meal_watcher/ ./meal_watcher/

RUN mkdir -p /data

CMD ["python", "-m", "meal_watcher.main"]
