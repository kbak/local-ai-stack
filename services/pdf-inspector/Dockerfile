FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016 AS builder

# Build stage: Rust toolchain + build deps. Discarded after wheel is built.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc g++ pkg-config libssl-dev ca-certificates git \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain 1.99.0 \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:$PATH"

RUN pip install --no-cache-dir maturin==1.15.0

ARG PDF_INSPECTOR_REV=f4b8c9e8546703e3817d9c47498d822cb2db81e3
RUN git clone https://github.com/firecrawl/pdf-inspector.git /pdf-inspector-src && \
    git -C /pdf-inspector-src checkout "${PDF_INSPECTOR_REV}" && \
    cd /pdf-inspector-src && \
    maturin build --release --out /wheels


FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

# Runtime: just the wheel + python deps. No rust, no build tools.
RUN apt-get update && \
    apt-get install -y --no-install-recommends poppler-utils && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder /wheels /wheels
COPY services/pdf-inspector/requirements.txt services/pdf-inspector/constraints.txt /tmp/
RUN pip install --no-cache-dir -c /tmp/constraints.txt -r /tmp/requirements.txt /wheels/*.whl && \
    rm -rf /wheels

WORKDIR /app
COPY shared/ /shared/
RUN pip install --no-cache-dir --no-deps -e /shared/
COPY services/pdf-inspector/server.py ./server.py

EXPOSE 8085

CMD ["python", "server.py"]
