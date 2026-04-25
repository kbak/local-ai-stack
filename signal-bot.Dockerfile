FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bump UOLTZ_REV (any new value) to force a fresh git clone of kbak/uoltz.
# Otherwise Docker caches the clone layer indefinitely and pushes to the
# fork won't be picked up by `docker compose build`.
ARG UOLTZ_REV=2026-04-25d
RUN echo "uoltz rev: ${UOLTZ_REV}" && git clone https://github.com/kbak/uoltz.git /uoltz
RUN pip install --no-cache-dir -r /uoltz/app/requirements.txt && \
    pip install --no-cache-dir mutagen && \
    pip install --no-cache-dir -U yt-dlp && \
    pip install --no-cache-dir lingua-language-detector

# stack_shared (resolve_model, etc.). Installed editable at /shared so the
# compose bind-mount of ./shared:/shared:ro picks up source changes without
# rebuilding the image.
COPY shared/ /shared/
RUN pip install --no-cache-dir --no-deps -e /shared/

RUN cp -r /uoltz/app/. .

CMD ["python", "bot.py"]
