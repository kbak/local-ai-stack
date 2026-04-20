FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY memory-mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Bake bge-m3 into the image so first-run has no download delay.
# ~2.3GB — matches the pattern used by audio-api (whisper + kokoro).
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

COPY memory-mcp/app /app/app

EXPOSE 8089

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8089"]
