#!/usr/bin/env bash
set -euo pipefail
STACK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="$STACK_ROOT/.maintenance/audiobook"
export UV_CACHE_DIR="$RUNTIME_DIR/uv-cache"
export HF_HOME="$RUNTIME_DIR/hf-cache"
mkdir -p "$RUNTIME_DIR/vendor"
if [[ ! -d "$RUNTIME_DIR/vendor/fish-speech/.git" ]]; then
  git clone https://github.com/fishaudio/fish-speech.git "$RUNTIME_DIR/vendor/fish-speech"
fi
git -C "$RUNTIME_DIR/vendor/fish-speech" checkout --detach 214da3cd841bda85da2496b96cd3c4d7edb1337e
if [[ ! -x "$RUNTIME_DIR/fish-venv/bin/python" ]]; then
  uv venv --python /usr/bin/python3 "$RUNTIME_DIR/fish-venv"
fi
uv pip install --python "$RUNTIME_DIR/fish-venv/bin/python" --index-url https://download.pytorch.org/whl/cu128 torch==2.8.0 torchaudio==2.8.0
uv pip install --python "$RUNTIME_DIR/fish-venv/bin/python" --override "$STACK_ROOT/scripts/audiobook/fish-overrides.txt" -r "$STACK_ROOT/scripts/audiobook/fish-requirements.lock"
hf download fishaudio/s2-pro --revision 1de9996b6be38b745688de084d87a5633f714e4e --local-dir "$RUNTIME_DIR/models/Fish-S2-Pro"
hf download deepdml/faster-whisper-large-v3-turbo-ct2 --revision 4df90f75321148c3a29a9e2351b7ddf8f5b115a8 --local-dir "$RUNTIME_DIR/models/whisper-large-v3-turbo"
