FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY voice-agent/requirements.txt voice-agent/constraints.txt /app/
RUN pip install --no-cache-dir -c /app/constraints.txt -r /app/requirements.txt

COPY shared/ /shared/
RUN pip install --no-cache-dir --no-deps /shared/
COPY signal-bot-custom-skills/ /app/skills/

COPY voice-agent/app /app/app
COPY voice-agent/static /app/static

ARG STACK_REVISION=dev
LABEL org.opencontainers.image.revision=$STACK_REVISION

EXPOSE 8087

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8087"]
