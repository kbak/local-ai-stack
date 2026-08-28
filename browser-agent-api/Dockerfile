FROM python:3.12-slim

ENV IN_DOCKER=true \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY browser-agent-api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt && \
    browser-use install

COPY browser-agent-api/app /app/app

RUN useradd --create-home --uid 10001 browser-agent && \
    mkdir -p /data/downloads /data/profiles && \
    chown -R browser-agent:browser-agent /app /data /ms-playwright

USER browser-agent

EXPOSE 8092

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8092"]
