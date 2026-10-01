FROM python:3.12-slim
RUN pip install --no-cache-dir httpx
WORKDIR /app
COPY shared/ /shared/
RUN pip install --no-cache-dir --no-deps -e /shared/
COPY public-egress/server.py ./server.py
USER 10001:10001
EXPOSE 8094
CMD ["python", "server.py"]
