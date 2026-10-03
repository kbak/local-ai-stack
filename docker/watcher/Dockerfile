FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36 AS watcher

COPY --from=ghcr.io/astral-sh/uv@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 /uv /usr/local/bin/uv
WORKDIR /app
ARG SERVICE
ARG MODULE
ARG SYSTEM_PACKAGES=ca-certificates
RUN apt-get update && apt-get install -y --no-install-recommends ${SYSTEM_PACKAGES} \
    && rm -rf /var/lib/apt/lists/*

# Each service retains its own dependency lock and installed environment.
COPY shared/pyproject.toml /shared/pyproject.toml
COPY services/${SERVICE}/pyproject.toml services/${SERVICE}/uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt && \
    grep -v '^-e ' /tmp/requirements.txt > /tmp/requirements-filtered.txt && \
    pip install --no-cache-dir -r /tmp/requirements-filtered.txt
COPY shared/ /shared/
RUN pip install --no-cache-dir --no-deps /shared/
COPY services/${SERVICE}/${MODULE}/ /app/${MODULE}/
RUN mkdir -p /data /travel-attachments

ARG STACK_REVISION=dev
LABEL org.opencontainers.image.revision=$STACK_REVISION
# Compose supplies the service-specific Python module.
CMD ["python"]

FROM watcher AS telegram
COPY services/tg-watcher/auth.py /app/auth.py
