FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

COPY audio-api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

RUN mkdir -p /app/kokoro-models && \
    python -c "\
import urllib.request; \
base = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0'; \
urllib.request.urlretrieve(base + '/kokoro-v1.0.fp16.onnx', '/app/kokoro-models/kokoro-v1.0.fp16.onnx'); \
urllib.request.urlretrieve(base + '/kokoro-v1.0.int8.onnx', '/app/kokoro-models/kokoro-v1.0.int8.onnx'); \
urllib.request.urlretrieve(base + '/voices-v1.0.bin', '/app/kokoro-models/voices-v1.0.bin') \
"

COPY audio-api/app /app/app

EXPOSE 8088

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
