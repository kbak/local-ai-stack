FROM python:3.12-slim

RUN pip install --no-cache-dir \
    "fastmcp<4" "mcp<2" \
    httpx \
    beautifulsoup4 \
    uvicorn \
    starlette

WORKDIR /app
COPY reverse-image-search/server.py ./server.py

EXPOSE 8091

CMD ["python", "server.py"]
