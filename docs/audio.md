# Audio and voice chat

`audio-api` serves Whisper transcription, Kokoro speech synthesis, and one
voice-cloning backend. VoxCPM2 is the default; Chatterbox is optional. Models
remain loaded and inference is serialized to bound GPU workspace use.

## Configure audio

Copy `examples/env/audio-api.env.example` to `audio-api.env`. Select exactly one device using
`SECONDARY_GPU` in `.env`. Optionally set `EXPECTED_AUDIO_GPU` to the device name
reported by PyTorch to detect an incorrect assignment.

`DEFAULT_VOICE`, `DEFAULT_LANG`, and `DEFAULT_SPEED` control requests that omit
those fields. Signal also reads `TTS_VOICE` from `signal-bot.env`, and LibreChat
has a UI voice default in `config/librechat.yaml`. Recreate audio-api after changing its
environment:

```bash
docker compose -f docker-compose.ai.yml up -d --no-deps audio-api
```

Reference WAV files live under `VOICE_SAMPLES_DIR`; their filename stems are
voice names. The directory is mounted read-only into audio-api and read-write
into Signal for sample creation. Set `CLONE_BACKEND=chatterbox` in `audio-api.env`
to select the alternative backend. Only the selected backend loads.

## Interfaces

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/audio/transcriptions` | Whisper transcription |
| `POST /v1/audio/speech` | Kokoro TTS; optional sentence streaming |
| `POST /v1/audio/clone` | Voice cloning: `text`, `voice`, `language`, `response_format` |
| `GET /v1/voices` | Kokoro voices |
| `GET /health` | Model readiness |
| `/mcp/mcp` | Voice-cloning MCP tools |

Cloning accepts a reference voice or unconditioned generation. VoxCPM2 uses the
text's language without translation; Chatterbox-specific `exaggeration` and
`cfg_weight` fields only affect that backend. Supported output formats include
WAV, MP3, Ogg/Opus, AAC/M4A, FLAC, and PCM. VoxCPM2 WAV uses native 48 kHz output;
raw PCM uses mono 24 kHz.

## Browser voice chat

`voice-agent` serves a microphone interface on port 8087. It streams audio to
speech recognition, invokes the LLM and tools, then streams synthesized speech
back. It supports conversation mode, interruption, and a per-session voice
selection populated from audio-api.

Microphone access requires a secure browser context. For remote access, use an
HTTPS proxy or a private-network HTTPS endpoint, for example:

```bash
tailscale serve --bg --https=8443 http://localhost:8087
```

Use a free port on your host and open the resulting URL on your client device.

## Evaluation

`services/audio-api/evaluation/` contains manual listening and transcription checks.
Run candidates sequentially on an explicitly selected GPU UUID. Set
`EVAL_EN_VOICE` and `EVAL_PL_VOICE` to reference filenames available on that host.
Generated clips and reports belong outside the repository.
