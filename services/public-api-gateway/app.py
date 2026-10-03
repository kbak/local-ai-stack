"""Strict public OpenAI-compatible gateway for the local llama-swap service.

The gateway intentionally has no catch-all proxy behavior: only /v1/* is
eligible, every eligible request requires the configured bearer key, and
model-bearing requests are limited to the explicit allowlist.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator
from urllib.parse import unquote, urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask


LOG = logging.getLogger("public_api_gateway")

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

# Keep the public surface to the OpenAI-compatible text-generation APIs needed
# by the selected chat models. In particular, vLLM-specific tokenize, LoRA,
# metrics, docs, and management routes are intentionally absent.
OPENAI_ROUTES = {
    ("GET", "/v1/models"),
    ("HEAD", "/v1/models"),
    ("POST", "/v1/chat/completions"),
    ("POST", "/v1/completions"),
    ("POST", "/v1/responses"),
}

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "CDN-Cache-Control": "no-store",
    "Cloudflare-CDN-Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Accel-Buffering": "no",
}


@dataclass(frozen=True)
class Settings:
    bearer_key: str
    models: frozenset[str]
    upstream: str
    max_body_bytes: int

    @classmethod
    def from_environment(cls) -> "Settings":
        bearer_key = os.environ.get("PUBLIC_API_BEARER_KEY", "")
        if len(bearer_key) < 32 or bearer_key.lower().startswith("replace"):
            raise RuntimeError(
                "PUBLIC_API_BEARER_KEY must be a non-placeholder value of at least 32 characters"
            )

        models = frozenset(
            model.strip()
            for model in os.environ.get("PUBLIC_API_MODELS", "").split(",")
            if model.strip()
        )
        if not models:
            raise RuntimeError("PUBLIC_API_MODELS must contain at least one model")

        upstream = os.environ.get("PUBLIC_API_UPSTREAM", "http://[::1]:8080").rstrip("/")
        parsed = urlsplit(upstream)
        if parsed.scheme != "http" or parsed.hostname not in {"::1", "127.0.0.1", "localhost"}:
            raise RuntimeError("PUBLIC_API_UPSTREAM must be an HTTP loopback URL")
        if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise RuntimeError("PUBLIC_API_UPSTREAM must contain only scheme, host, and port")

        max_body_bytes = int(os.environ.get("PUBLIC_API_MAX_BODY_BYTES", "10485760"))
        if max_body_bytes < 1:
            raise RuntimeError("PUBLIC_API_MAX_BODY_BYTES must be positive")

        return cls(
            bearer_key=bearer_key,
            models=models,
            upstream=upstream,
            max_body_bytes=max_body_bytes,
        )


def _json_error(status_code: int, message: str, error_type: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": error_type}},
        headers=NO_CACHE_HEADERS,
    )


def _is_v1_path(path: str) -> bool:
    return path.startswith("/v1/")


def _is_openai_route(method: str, path: str, raw_path: bytes) -> bool:
    raw_path_lower = raw_path.lower()
    if any(encoded in raw_path_lower for encoded in (b"%2e", b"%2f", b"%5c")):
        return False
    if "\\" in path or "//" in path or any(
        segment in {".", ".."} for segment in path.split("/")
    ):
        return False
    if (method, path) in OPENAI_ROUTES:
        return True
    return method in {"GET", "HEAD"} and path.startswith("/v1/models/")


def _model_from_request(path: str, query_model: str | None, body: bytes) -> str | None:
    model_path_prefix = "/v1/models/"
    if path.startswith(model_path_prefix):
        model = unquote(path[len(model_path_prefix) :])
        return model or None

    if body:
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        model = payload.get("model")
        return model if isinstance(model, str) and model else None

    return query_model or None


def _request_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in request.headers.items():
        lowered = name.lower()
        if lowered in HOP_BY_HOP_HEADERS or lowered in {
            "authorization",
            "content-length",
            "host",
        }:
            continue
        headers[name] = value
    return headers


def _response_headers(response: httpx.Response) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in response.headers.items():
        lowered = name.lower()
        if lowered in HOP_BY_HOP_HEADERS or lowered in {
            "content-length",
            "cache-control",
            "cdn-cache-control",
            "cloudflare-cdn-cache-control",
            "expires",
            "pragma",
        }:
            continue
        headers[name] = value
    headers.update(NO_CACHE_HEADERS)
    return headers


def _filtered_models_response(
    response: httpx.Response, allowed_models: frozenset[str]
) -> Response:
    headers = _response_headers(response)
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=headers,
        )

    if response.is_success and isinstance(payload, dict) and isinstance(payload.get("data"), list):
        payload["data"] = [
            entry
            for entry in payload["data"]
            if isinstance(entry, dict) and entry.get("id") in allowed_models
        ]
    return JSONResponse(content=payload, status_code=response.status_code, headers=headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=None, write=60.0, pool=30.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
        yield
        await app.state.client.aclose()

    app = FastAPI(
        title="Local OpenAI public gateway",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.api_route(
        "/{public_path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def proxy(request: Request, public_path: str) -> Response:
        del public_path
        path = request.url.path

        # Path filtering intentionally precedes authentication so management
        # endpoints are indistinguishable from nonexistent routes.
        if not _is_v1_path(path):
            return Response(status_code=404, headers=NO_CACHE_HEADERS)

        expected = f"Bearer {resolved_settings.bearer_key}"
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            return _json_error(401, "Invalid or missing bearer token", "authentication_error")

        if not _is_openai_route(
            request.method,
            path,
            request.scope.get("raw_path", path.encode()),
        ):
            return Response(status_code=404, headers=NO_CACHE_HEADERS)

        declared_length = request.headers.get("content-length")
        if declared_length:
            try:
                if int(declared_length) > resolved_settings.max_body_bytes:
                    return _json_error(413, "Request body is too large", "invalid_request_error")
            except ValueError:
                return _json_error(400, "Invalid Content-Length", "invalid_request_error")

        body = await request.body()
        if len(body) > resolved_settings.max_body_bytes:
            return _json_error(413, "Request body is too large", "invalid_request_error")

        is_models_index = path == "/v1/models" and request.method in {"GET", "HEAD"}
        if not is_models_index:
            model = _model_from_request(path, request.query_params.get("model"), body)
            if model not in resolved_settings.models:
                return _json_error(
                    404,
                    "The requested model is not available on this endpoint",
                    "model_not_found",
                )

        upstream_url = f"{resolved_settings.upstream}{path}"
        if request.url.query:
            upstream_url = f"{upstream_url}?{request.url.query}"

        client: httpx.AsyncClient = request.app.state.client
        upstream_request = client.build_request(
            request.method,
            upstream_url,
            headers=_request_headers(request),
            content=body,
        )
        try:
            upstream_response = await client.send(upstream_request, stream=True)
        except httpx.HTTPError:
            LOG.exception("Upstream request failed for %s", path)
            return _json_error(502, "The local model gateway is unavailable", "upstream_error")

        if is_models_index:
            await upstream_response.aread()
            try:
                return _filtered_models_response(upstream_response, resolved_settings.models)
            finally:
                await upstream_response.aclose()

        return StreamingResponse(
            upstream_response.aiter_raw(),
            status_code=upstream_response.status_code,
            headers=_response_headers(upstream_response),
            background=BackgroundTask(upstream_response.aclose),
        )

    return app


app = create_app()
