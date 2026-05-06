FROM python:3.13-slim

# Install build deps, runtime tools, and gh (GitHub CLI) for the gh_read tool.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ nodejs npm git curl ca-certificates \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | dd of=/etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Install uv (provides uvx)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Build and install mcp-proxy from upstream main
RUN git clone --depth 1 https://github.com/sparfenyuk/mcp-proxy.git /mcp-proxy-src && \
    pip install --no-cache-dir /mcp-proxy-src && \
    rm -rf /mcp-proxy-src

# Install the MCP SDK for the bundled stdio servers (gh-read, gmaps shim).
RUN pip install --no-cache-dir "mcp>=1.2.0"

# Runtime shim that patches google-maps-mcp-server's PlacesTool to use
# searchText instead of its broken searchNearby+keyword-filter combo.
COPY gmaps-searchtext-shim.py /opt/gmaps-searchtext-shim.py

# Thin read-only GitHub MCP server (replaces @modelcontextprotocol/server-github).
# One tool (gh_read) instead of 26 — uses the gh CLI with GITHUB_TOKEN from env.
COPY gh-read-server.py /opt/gh-read-server.py

# Pre-install all MCP packages at pinned versions so first connection doesn't time out
RUN uvx google-maps-mcp-server==0.2.1 --help 2>/dev/null || true && \
    uvx mcp-server-fetch==2025.4.7 --help 2>/dev/null || true && \
    uvx arxiv-mcp-server==0.4.11 --help 2>/dev/null || true && \
    uvx mcp-youtube-transcript==0.3.5 --help 2>/dev/null || true && \
    uvx mcp-server-time==2026.1.26 --help 2>/dev/null || true && \
    uvx mcp-hn==0.1.0 --help 2>/dev/null || true && \
    uvx mcp-pdf-reader==0.1.7 --help 2>/dev/null || true && \
    uvx --from mcp-weather-server==0.6.1 mcp_weather_server --help 2>/dev/null || true && \
    uvx frankfurtermcp==0.4.4 --help 2>/dev/null || true && \
    uvx yfinance-mcp-server==1.0.4 --help 2>/dev/null || true && \
    uvx mcp-searxng==0.1.0 --help 2>/dev/null || true && \
    rm -rf /root/.cache/uv/builds-v0 /root/.cache/uv/sdists-v* /root/.cache/uv/git-v0 2>/dev/null || true

ENTRYPOINT ["mcp-proxy"]
