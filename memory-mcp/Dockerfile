FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY memory-mcp/requirements.txt /app/requirements.txt
# Install CPU-only torch first so sentence-transformers picks it up as
# already-satisfied instead of pulling the cu* wheels (~4.5 GB of unused
# CUDA libs). bge-m3 runs on CPU here — this container has no GPU access.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
        torch torchvision && \
    pip install --no-cache-dir -r /app/requirements.txt

# Install stack_shared editable so a compose bind-mount of ./shared:/shared:ro
# picks up source changes without rebuilding. --no-deps because memory-mcp
# doesn't need apscheduler/caldav/icalendar from stack_shared's dep list;
# httpx + openai come from its own requirements.
COPY shared/ /shared/
RUN pip install --no-cache-dir --no-deps -e /shared/

# Bake bge-m3 into the image so first-run has no download delay.
# ~2.3GB - matches the pattern used by audio-api (whisper + kokoro).
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

COPY memory-mcp/app /app/app

EXPOSE 8089

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8089"]
