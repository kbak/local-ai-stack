FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone our fork and install dependencies
RUN git clone https://github.com/kbak/uoltz.git /uoltz
RUN pip install --no-cache-dir -r /uoltz/app/requirements.txt && \
    pip install --no-cache-dir mutagen && \
    pip install --no-cache-dir -U yt-dlp

# Copy uoltz app as base
RUN cp -r /uoltz/app/. .

# Pre-download the Whisper model
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"

# Pre-download the Kokoro ONNX model files
RUN mkdir -p /app/kokoro-models && \
    python -c "\
import urllib.request; \
base = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0'; \
print('Downloading kokoro-v1.0.int8.onnx...'); \
urllib.request.urlretrieve(base + '/kokoro-v1.0.int8.onnx', '/app/kokoro-models/kokoro-v1.0.int8.onnx'); \
print('Downloading voices-v1.0.bin...'); \
urllib.request.urlretrieve(base + '/voices-v1.0.bin', '/app/kokoro-models/voices-v1.0.bin'); \
print('Done.') \
"

CMD ["python", "bot.py"]
