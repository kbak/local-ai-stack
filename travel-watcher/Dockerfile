FROM python:3.12-slim

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends libssl-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY shared/ /shared/
COPY travel-watcher/pyproject.toml ./
COPY travel-watcher/travel_watcher/ ./travel_watcher/
RUN uv pip install --system . /shared
RUN mkdir -p /data /travel-attachments

CMD ["python", "-m", "travel_watcher.main"]
