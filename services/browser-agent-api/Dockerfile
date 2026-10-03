FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

ENV IN_DOCKER=true \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/browser-agent-api/requirements.txt services/browser-agent-api/constraints.txt /app/
RUN pip install --no-cache-dir -c /app/constraints.txt -r /app/requirements.txt && \
    browser-use install

COPY shared/ /shared/
RUN pip install --no-cache-dir --no-deps -e /shared/
COPY services/browser-agent-api/app /app/app

RUN useradd --create-home --uid 10001 browser-agent && \
    mkdir -p /data/downloads /data/profiles && \
    chown -R browser-agent:browser-agent /app /data /ms-playwright

USER browser-agent

EXPOSE 8092

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8092"]
