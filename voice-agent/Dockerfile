FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY voice-agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Install stack_shared editable so a compose bind-mount of ./shared:/shared:ro
# picks up source changes without rebuilding the image. --no-deps because
# voice-agent's requirements.txt already provides what it needs (openai,
# httpx) and stack_shared's transitive deps (apscheduler, caldav, etc.) are
# unused here.
COPY shared/ /shared/
RUN pip install --no-cache-dir --no-deps -e /shared/

COPY voice-agent/app /app/app
COPY voice-agent/static /app/static

EXPOSE 8087

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8087"]
