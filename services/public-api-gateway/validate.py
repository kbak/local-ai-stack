"""End-to-end validation for the protected public API gateway."""

from __future__ import annotations

import json
import os
import sys
import time

import httpx


BASE_URL = os.environ.get("PUBLIC_API_BASE_URL", "http://127.0.0.1:8093").rstrip("/")
BEARER_KEY = os.environ["PUBLIC_API_BEARER_KEY"]
AUTH = {"Authorization": f"Bearer {BEARER_KEY}"}
EXPECTED_MODELS = {"qwen3.8-27B-FP8", "qwen3.6-35B-A3B-FP8"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def status(client: httpx.Client, path: str, expected: int, headers=None) -> None:
    response = client.get(f"{BASE_URL}{path}", headers=headers)
    require(response.status_code == expected, f"{path}: expected {expected}, got {response.status_code}")
    print(f"{path}: {response.status_code}")


def main() -> int:
    timeout = httpx.Timeout(connect=5, read=900, write=30, pool=5)
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        models = client.get(f"{BASE_URL}/v1/models", headers=AUTH)
        require(models.status_code == 200, f"authorized /v1/models returned {models.status_code}")
        advertised = {entry["id"] for entry in models.json().get("data", [])}
        require(advertised == EXPECTED_MODELS, f"unexpected model allowlist: {sorted(advertised)}")
        require("no-store" in models.headers.get("cache-control", ""), "missing no-store header")
        print(f"/v1/models: 200, models={','.join(sorted(advertised))}, cache=no-store")

        status(client, "/v1/models", 401)
        status(client, "/v1/models", 401, {"Authorization": "Bearer invalid"})

        for blocked_path in ("/invocations", "/metrics", "/docs", "/"):
            status(client, blocked_path, 404)

        status(client, "/v1/%2e%2e/metrics", 404, AUTH)
        status(client, "/v1/tokenize", 404, AUTH)

        blocked_management = client.post(
            f"{BASE_URL}/v1/load_lora_adapter",
            headers=AUTH,
            json={"model": "qwen3.8-27B-FP8"},
        )
        require(blocked_management.status_code == 404, "vLLM management route was not blocked")
        print("/v1/load_lora_adapter: 404")

        blocked_model = client.post(
            f"{BASE_URL}/v1/chat/completions",
            headers=AUTH,
            json={
                "model": "qwen-coder-7B",
                "messages": [{"role": "user", "content": "Reply OK"}],
                "max_tokens": 2,
            },
        )
        require(blocked_model.status_code == 404, "unselected model was not blocked")
        print("unselected model: 404")

        payload = {
            "model": "qwen3.8-27B-FP8",
            "messages": [{"role": "user", "content": "Reply with exactly OK."}],
            "max_tokens": 8,
            "temperature": 0,
        }
        completion = client.post(
            f"{BASE_URL}/v1/chat/completions",
            headers=AUTH,
            json=payload,
        )
        require(completion.status_code == 200, f"chat completion returned {completion.status_code}")
        require(completion.json().get("choices"), "chat completion returned no choices")
        print("chat completion: 200")

        stream_payload = dict(payload, stream=True, max_tokens=16)
        started = time.monotonic()
        with client.stream(
            "POST",
            f"{BASE_URL}/v1/chat/completions",
            headers={**AUTH, "Content-Type": "application/json"},
            content=json.dumps(stream_payload),
        ) as stream:
            require(stream.status_code == 200, f"stream returned {stream.status_code}")
            require(
                stream.headers.get("content-type", "").startswith("text/event-stream"),
                f"unexpected stream content type: {stream.headers.get('content-type')}",
            )
            headers_received = time.monotonic()
            chunks = []
            first_chunk_delay = None
            for chunk in stream.iter_bytes():
                if not chunk:
                    continue
                if first_chunk_delay is None:
                    first_chunk_delay = time.monotonic() - headers_received
                chunks.append(chunk)
            body = b"".join(chunks)

        require(first_chunk_delay is not None, "stream returned no chunks")
        require(first_chunk_delay < 2.0, f"first SSE chunk was buffered for {first_chunk_delay:.3f}s")
        require(body.count(b"data:") >= 2, "stream did not contain multiple SSE events")
        require(b"[DONE]" in body, "stream did not terminate with [DONE]")
        print(
            "stream: 200, content-type=text/event-stream, "
            f"first-chunk-after-headers={first_chunk_delay:.3f}s, total={time.monotonic() - started:.3f}s"
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, httpx.HTTPError) as error:
        print(f"validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
