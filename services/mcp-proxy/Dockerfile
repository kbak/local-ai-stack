FROM python:3.13-slim@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81

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
COPY --from=ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 /uv /uvx /usr/local/bin/

COPY requirements.txt constraints.txt /tmp/

# Build and install a reviewed mcp-proxy revision instead of a moving main branch.
ARG MCP_PROXY_REV=153a96a61fde2bf5a23961c64a3dd96b5e385108
RUN git clone https://github.com/sparfenyuk/mcp-proxy.git /mcp-proxy-src && \
    git -C /mcp-proxy-src checkout "${MCP_PROXY_REV}" && \
    pip install --no-cache-dir -c /tmp/constraints.txt /mcp-proxy-src -r /tmp/requirements.txt && \
    rm -rf /mcp-proxy-src

# Install the MCP SDK for the bundled stdio servers (gh-read, gmaps shim).
# The MCP SDK is included in the locked requirements above.

# Runtime shim that patches google-maps-mcp-server's PlacesTool to use
# searchText instead of its broken searchNearby+keyword-filter combo.
COPY gmaps-searchtext-shim.py /opt/gmaps-searchtext-shim.py

# Thin read-only GitHub MCP server (replaces @modelcontextprotocol/server-github).
# One tool (gh_read) instead of 26 — uses the gh CLI with GITHUB_TOKEN from env.
COPY gh-read-server.py /opt/gh-read-server.py
COPY browser-agent-server.py /opt/browser-agent-server.py

# Match the Maps shim's runtime environment; uvx creates a different cache entry.
RUN uv run --with google-maps-mcp-server==0.2.1 --with mcp==1.30.0 \
    python -c "from google_maps_mcp_server.tools.places import PlacesTool"

# Pre-install all MCP packages at pinned versions so first connection doesn't time out
RUN uvx google-maps-mcp-server==0.2.1 --help 2>/dev/null || true && \
    uvx --with mcp==1.30.0 mcp-server-fetch==2026.8.18 --help 2>/dev/null || true && \
    uvx --with mcp==1.30.0 arxiv-mcp-server==0.8.0 --help 2>/dev/null || true && \
    uvx --with mcp==1.30.0 mcp-youtube-transcript==0.3.5 --help 2>/dev/null || true && \
    uvx --with mcp==1.30.0 mcp-server-time==2026.8.18 --help 2>/dev/null || true && \
    uvx --with mcp==1.30.0 mcp-hn==0.1.0 --help 2>/dev/null || true && \
    uvx --with mcp==1.30.0 mcp-pdf-reader==0.1.7 --help 2>/dev/null || true && \
    uvx --with mcp==1.30.0 --from mcp-weather-server==0.6.1 mcp_weather_server --help 2>/dev/null || true && \
    uvx --with mcp==1.30.0 frankfurtermcp==0.5.0 --help 2>/dev/null || true && \
    uvx --with mcp==1.30.0 yfinance-mcp-server==1.0.4 --help 2>/dev/null || true && \
    rm -rf /root/.cache/uv/builds-v0 /root/.cache/uv/git-v0 2>/dev/null || true

# Keep frequently edited local servers after dependency warm-up for fast rebuilds.
COPY searxng-server.py /opt/searxng-server.py

ENTRYPOINT ["mcp-proxy"]
