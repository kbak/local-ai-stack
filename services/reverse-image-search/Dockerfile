FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

COPY services/reverse-image-search/requirements.txt services/reverse-image-search/constraints.txt /tmp/
RUN pip install --no-cache-dir -c /tmp/constraints.txt -r /tmp/requirements.txt

WORKDIR /app
COPY shared/ /shared/
RUN pip install --no-cache-dir --no-deps -e /shared/
COPY services/reverse-image-search/server.py ./server.py

EXPOSE 8091

CMD ["python", "server.py"]
