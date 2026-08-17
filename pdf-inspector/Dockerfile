FROM python:3.12-slim AS builder

# Build stage: Rust toolchain + build deps. Discarded after wheel is built.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc g++ pkg-config libssl-dev ca-certificates git \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:$PATH"

RUN pip install --no-cache-dir maturin

ARG PDF_INSPECTOR_REV=f4b8c9e8546703e3817d9c47498d822cb2db81e3
RUN git clone https://github.com/firecrawl/pdf-inspector.git /pdf-inspector-src && \
    git -C /pdf-inspector-src checkout "${PDF_INSPECTOR_REV}" && \
    cd /pdf-inspector-src && \
    maturin build --release --out /wheels


FROM python:3.12-slim

# Runtime: just the wheel + python deps. No rust, no build tools.
RUN apt-get update && \
    apt-get install -y --no-install-recommends poppler-utils && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir httpx fastmcp /wheels/*.whl && \
    rm -rf /wheels

WORKDIR /app
COPY pdf-inspector/server.py ./server.py

EXPOSE 8085

CMD ["python", "server.py"]
