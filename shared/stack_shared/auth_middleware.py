"""Starlette bearer token auth middleware shared by all internal MCP servers."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str):
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        if self._token:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {self._token}":
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)
