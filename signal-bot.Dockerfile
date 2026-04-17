FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git espeak-ng && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone our fork and install dependencies
RUN git clone https://github.com/kbak/uoltz.git /uoltz
RUN pip install --no-cache-dir -r /uoltz/app/requirements.txt && \
    pip install --no-cache-dir mutagen && \
    pip install --no-cache-dir -U yt-dlp

# Copy uoltz app as base
RUN cp -r /uoltz/app/. .

# Pre-download the whisper model
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"

# Pre-download the Kokoro TTS model
RUN python -c "from kokoro import KPipeline; KPipeline(lang_code='a')"

CMD ["python", "bot.py"]
