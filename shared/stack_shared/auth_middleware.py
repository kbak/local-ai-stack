"""Starlette bearer token auth middleware shared by all internal MCP servers."""

from __future__ import annotations

import secrets

from starlette.responses import JSONResponse


class BearerAuthMiddleware:
    """Authenticate before routing, including mounted MCP and SSE transports."""

    def __init__(self, app, token: str, public_paths: tuple[str, ...] = ()):
        if not token or token != token.strip():
            raise ValueError("A non-empty bearer token is required")
        self.app = app
        self._authorization = f"Bearer {token}".encode()
        self._public_paths = frozenset(public_paths)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        if (scope["type"] == "http" and scope.get("method") in {"GET", "HEAD"}
                and scope.get("path") in self._public_paths):
            return await self.app(scope, receive, send)
        credentials = [value for name, value in scope.get("headers", [])
                       if name.lower() == b"authorization"]
        if len(credentials) != 1 or not secrets.compare_digest(credentials[0], self._authorization):
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            response = JSONResponse({"error": "Unauthorized"}, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)
