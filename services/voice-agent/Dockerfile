FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/voice-agent/requirements.txt services/voice-agent/constraints.txt /app/
RUN pip install --no-cache-dir -c /app/constraints.txt -r /app/requirements.txt

COPY shared/ /shared/
RUN pip install --no-cache-dir --no-deps /shared/
COPY services/signal-bot/skills/ /app/skills/

COPY services/voice-agent/app /app/app
COPY services/voice-agent/static /app/static

ARG STACK_REVISION=dev
LABEL org.opencontainers.image.revision=$STACK_REVISION

EXPOSE 8087

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8087"]
