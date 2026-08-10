# GPU host upgrade — 2026-08-10

The GPU host runs `docker-compose.ai.yml` (Qdrant, memory-mcp, audio-api) plus
native llama-swap and vLLM. `docker-compose.server.yml` is the Lenovo host and
was deliberately not changed or redeployed; its upgrade is commit `fc812da`.

## Deployed versions

- Qdrant 1.18.2
- memory-mcp: mem0ai 2.0.13, qdrant-client 1.18.0,
  sentence-transformers 3.3.1, FastAPI 0.139.2, Uvicorn 0.51.0, HTTPX 0.28.1,
  python-multipart 0.0.32, MCP SDK 1.28.1
- audio-api: FastAPI 0.139.2, Uvicorn 0.51.0, HTTPX 0.28.1,
  python-multipart 0.0.32, MCP SDK 1.28.1; retained faster-whisper 1.2.1,
  kokoro-onnx 0.4.6, onnxruntime-gpu 1.23.2, Chatterbox 0.1.7,
  PyTorch/Torchaudio 2.11.0+cu128, and Transformers 5.2.0
- Native inference retained vLLM 0.20.1 with PyTorch 2.11.0+cu130 and
  Transformers 5.8.0

## Backup

Before upgrading Qdrant, a full snapshot was downloaded outside Qdrant's live
storage and verified against Qdrant's reported SHA-256:

`/mnt/d/backup/sync/memory/qdrant-backups/20260810T000807Z/full-snapshot-2026-08-10-00-06-58.snapshot`

Size: 1,445,959,680 bytes  
SHA-256: `73e46ff61d55b97792e4393bb42820e19c9e9f9841266879ba2cfdd0f001fa13`

## vLLM 0.23 evaluation

vLLM 0.23.0 was intentionally deferred. It is a high-risk parser/model-runner
upgrade, and its known `/v1/models` HTTP 500 regression conflicts directly with
llama-swap's configured readiness check (`checkEndpoint: /v1/models`) for every
model. Replacing the working environment would risk breaking model lifecycle
before the Qwen 3.6 FP8 and parser matrix could be validated. The existing
0.20.1 runtime remains installed and passed 35B and 27B FP8 chat, reasoning,
automatic `qwen3_xml` tool calls, coder completion, reranking, aliases, lifecycle,
and GPU-allocation checks.

## External verification note

Lenovo-origin reachability could not be rerun because Tailscale SSH required an
interactive reauthentication. Local GPU endpoints and services passed, but the
LibreChat/Signal-bot checks from Lenovo remain an operator follow-up after
reauthenticating Tailscale SSH.
