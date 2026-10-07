#!/usr/bin/env bash
set -euo pipefail
STACK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$STACK_ROOT/.maintenance/audiobook"
export UV_CACHE_DIR="$RUNTIME_DIR/uv-cache"
export HF_HOME="$RUNTIME_DIR/hf-cache"
mkdir -p "$RUNTIME_DIR/vendor"
if [[ ! -d "$RUNTIME_DIR/vendor/breeze-tts/.git" ]]; then
  git clone https://github.com/breezeblue-ai/breeze-tts.git "$RUNTIME_DIR/vendor/breeze-tts"
fi
git -C "$RUNTIME_DIR/vendor/breeze-tts" checkout --detach 008f769016b0a24711becd7a4925030bc93f608c
if [[ ! -x "$RUNTIME_DIR/venv/bin/python" ]]; then
  uv venv --python /usr/bin/python3 "$RUNTIME_DIR/venv"
fi
uv pip install --python "$RUNTIME_DIR/venv/bin/python" --index-url https://download.pytorch.org/whl/cu128 torch==2.9.1 torchaudio==2.9.1
uv pip install --python "$RUNTIME_DIR/venv/bin/python" -r "$STACK_ROOT/audiobook/requirements.lock"
hf download BreezeBlue/Breeze-TTS-2 --revision 3e28c5151381a722f1d8661b4118c298caa77aa4 --local-dir "$RUNTIME_DIR/models/Breeze-TTS-2"
hf download deepdml/faster-whisper-large-v3-turbo-ct2 --revision 4df90f75321148c3a29a9e2351b7ddf8f5b115a8 --local-dir "$RUNTIME_DIR/models/whisper-large-v3-turbo"
