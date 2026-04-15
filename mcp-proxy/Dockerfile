FROM python:3.13-slim

# Install build deps and runtime tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ nodejs npm git \
    && rm -rf /var/lib/apt/lists/*

# Install uv (provides uvx)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Build and install mcp-proxy from upstream main
RUN git clone --depth 1 https://github.com/sparfenyuk/mcp-proxy.git /mcp-proxy-src && \
    pip install --no-cache-dir /mcp-proxy-src && \
    rm -rf /mcp-proxy-src

# Pre-install all MCP packages at pinned versions so first connection doesn't time out
RUN uvx mcp-server-fetch==2025.4.7 --help 2>/dev/null || true && \
    uvx wikipedia-mcp==2.0.0 --help 2>/dev/null || true && \
    uvx arxiv-mcp-server==0.4.11 --help 2>/dev/null || true && \
    uvx mcp-youtube-transcript==0.3.5 --help 2>/dev/null || true && \
    uvx mcp-server-time==2026.1.26 --help 2>/dev/null || true && \
    uvx mcp-hn==0.1.0 --help 2>/dev/null || true && \
    uvx mcp-pdf-reader==0.1.7 --help 2>/dev/null || true && \
    uvx semantic-scholar-mcp==0.4.0 --help 2>/dev/null || true && \
    uvx patent-mcp-server==0.8.0 --help 2>/dev/null || true && \
    uvx --from mcp-weather-server==0.6.1 mcp_weather_server --help 2>/dev/null || true && \
    uvx frankfurtermcp==0.4.4 --help 2>/dev/null || true && \
    uvx yfinance-mcp-server==1.0.4 --help 2>/dev/null || true && \
    uvx mcp-searxng==0.1.0 --help 2>/dev/null || true && \
    npx -y @modelcontextprotocol/server-github --help 2>/dev/null || true

ENTRYPOINT ["mcp-proxy"]
