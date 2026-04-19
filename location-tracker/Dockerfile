FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install system deps for caldav/ssl
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install shared library editable so a compose bind-mount of ./shared:/shared:ro
# picks up source changes without rebuilding the image.
COPY shared/ /shared/
RUN pip install --no-cache-dir -e /shared/

# Export locked deps to requirements.txt, then install — no runtime uv needed
# Exclude the local stack-shared path dep (already installed above)
COPY location-tracker/pyproject.toml location-tracker/uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt && \
    grep -v '^-e ' /tmp/requirements.txt > /tmp/requirements-filtered.txt && \
    pip install --no-cache-dir -r /tmp/requirements-filtered.txt

COPY location-tracker/location_tracker/ ./location_tracker/

# State volume mount point
RUN mkdir -p /data

CMD ["python", "-m", "location_tracker.mcp_server"]
