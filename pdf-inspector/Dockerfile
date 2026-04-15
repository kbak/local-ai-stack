FROM python:3.12-slim

# Install Rust toolchain + build deps for pdf-inspector
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc g++ pkg-config libssl-dev ca-certificates git \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:$PATH"

# Install Python build deps
RUN pip install --no-cache-dir maturin httpx fastmcp

# Build pdf-inspector Python bindings from source
RUN git clone --depth 1 https://github.com/firecrawl/pdf-inspector.git /pdf-inspector-src && \
    cd /pdf-inspector-src && \
    maturin build --release --out /tmp/wheels && \
    pip install --no-cache-dir /tmp/wheels/*.whl && \
    rm -rf /pdf-inspector-src /tmp/wheels

WORKDIR /app
COPY pdf-inspector/server.py ./server.py

EXPOSE 8085

CMD ["python", "server.py"]
