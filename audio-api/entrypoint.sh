#!/bin/bash
set -e

# phonemizer (transitively used by Kokoro) copies libespeak-ng.so to a fresh
# tempfile.mkdtemp() per EspeakAPI instance and relies on weakref.finalize
# for cleanup. Long-lived references in kokoro-onnx prevent finalization,
# leaking ~650 KB per TTS request.
(
  while sleep 3600; do
    find /tmp -maxdepth 1 -name 'tmp*' -type d -mmin +60 -exec rm -rf {} + 2>/dev/null || true
    find /tmp -maxdepth 1 -name 'tmp*.wav' -mmin +60 -delete 2>/dev/null || true
  done
) &

exec uvicorn app.main:app --host 0.0.0.0 --port 8088
