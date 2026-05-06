FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg python3 python3-pip git && \
    rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

# HF cache lives on a volume so model weights persist across rebuilds.
ENV HF_HOME=/app/hf-cache
RUN mkdir -p /app/hf-cache

# Step 1 — base requirements (whisper, kokoro-onnx, fastapi, MCP SDK).
COPY audio-api/requirements.txt /app/requirements-base.txt
RUN sed -i '/^chatterbox-tts/d' /app/requirements-base.txt && \
    pip install --no-cache-dir -r /app/requirements-base.txt && \
    pip uninstall -y onnxruntime && \
    pip install --no-cache-dir --force-reinstall onnxruntime-gpu==1.19.2

# Step 2 — torch / torchaudio from the cu128 index. Required for Blackwell
# (sm_120 — 5060 Ti / 5090). The cu128 wheels bundle their own CUDA runtime
# so the cu126 base image is fine — onnxruntime-gpu uses the system libs,
# torch uses its bundled libs.
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cu128 \
    "torch>=2.7" "torchaudio>=2.7"

# Step 3 — chatterbox-tts. Install with --no-deps so its hard pin on torch==2.6.0
# does not downgrade the cu128 wheels we just installed, then install its actual
# runtime deps explicitly (excluding torch/torchaudio which are already there).
RUN pip install --no-cache-dir --no-deps chatterbox-tts && \
    pip install --no-cache-dir \
        "numpy" \
        "librosa==0.11.0" \
        "s3tokenizer" \
        "transformers==5.2.0" \
        "diffusers==0.29.0" \
        "resemble-perth>=1.0.0" \
        "conformer==0.3.2" \
        "safetensors==0.5.3" \
        "spacy-pkuseg" \
        "pykakasi==2.3.0" \
        "pyloudnorm" \
        "omegaconf"

# Pre-download Whisper, Kokoro, and Chatterbox weights so first start is instant.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

RUN mkdir -p /app/kokoro-models && \
    python -c "\
import urllib.request; \
base = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0'; \
urllib.request.urlretrieve(base + '/kokoro-v1.0.fp16.onnx', '/app/kokoro-models/kokoro-v1.0.fp16.onnx'); \
urllib.request.urlretrieve(base + '/kokoro-v1.0.int8.onnx', '/app/kokoro-models/kokoro-v1.0.int8.onnx'); \
urllib.request.urlretrieve(base + '/voices-v1.0.bin', '/app/kokoro-models/voices-v1.0.bin') \
"

# Pre-download Chatterbox weights into HF_HOME so first container start does
# not have to fetch ~2 GB. Use device=cpu for the download step — actual
# inference at runtime uses cuda when available.
RUN python -c "from chatterbox.tts import ChatterboxTTS; ChatterboxTTS.from_pretrained(device='cpu')" || \
    echo "Chatterbox weight prefetch failed — first container start will download instead"

COPY audio-api/app /app/app
COPY audio-api/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8088

CMD ["/app/entrypoint.sh"]
