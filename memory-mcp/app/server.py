"""memory-mcp — HTTP + MCP front door for Mem0.

Two surfaces:
  * /health and /v1/*   — plain REST (for start.sh readiness checks and debugging)
  * /mcp                — MCP streamable-http endpoint for LibreChat, signal-bot, opencode

Both speak to the same Mem0 backend (bge-m3 local, qwen via llama-swap, Qdrant store).

Note: do NOT enable `from __future__ import annotations` here. FastMCP's tool
decorator runs `issubclass(param.annotation, Context)` on each parameter, which
fails with TypeError when annotations are stringified forward refs.
"""

import logging
from contextlib import asynccontextmanager

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP

from . import config, memory_backend

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("memory-mcp")


# ── MCP tools ───────────────────────────────────────────────────────────
# FastMCP exposes these as MCP tools over streamable-http. The same functions
# are also exposed via REST below so you can curl them during development.

mcp = FastMCP("memory-mcp")


@mcp.tool()
def add_memory(content: str, user_id: str = "", metadata_json: str = "") -> dict:
    """Save information to long-term memory.

    Call this when the user states a durable preference, a stable fact about
    themselves or their setup, or explicitly asks you to remember something.
    Do NOT call this for transient conversation, questions, or your own actions.

    Writes are asynchronous — this returns immediately and Mem0 extracts facts
    in the background. Safe to call mid-conversation without slowing the reply.

    `metadata_json`: optional JSON-encoded string of metadata to attach.
    """
    import json as _json
    uid = user_id or config.DEFAULT_USER_ID
    metadata = _json.loads(metadata_json) if metadata_json else None
    memory_backend.enqueue_add(content, user_id=uid, metadata=metadata)
    return {"queued": True, "user_id": uid, "pending": memory_backend.pending_writes()}


@mcp.tool()
def search_memory(query: str, user_id: str = "", limit: int = 5) -> dict:
    """Search long-term memory for relevant facts.

    Call this when you need context from past conversations, user preferences,
    or decisions that aren't already in your current context window.
    Returns the top matches ranked by semantic similarity.
    """
    uid = user_id or config.DEFAULT_USER_ID
    results = memory_backend.search(query=query, user_id=uid, limit=limit)
    return {"query": query, "user_id": uid, "results": results}


@mcp.tool()
def list_memories(user_id: str = "", limit: int = 100) -> dict:
    """List all stored memories for a user. Useful for auditing or pruning."""
    uid = user_id or config.DEFAULT_USER_ID
    results = memory_backend.list_all(user_id=uid, limit=limit)
    return {"user_id": uid, "count": len(results), "results": results}


@mcp.tool()
def delete_memory(memory_id: str) -> dict:
    """Delete a specific memory by its ID (from list_memories / search_memory results)."""
    memory_backend.delete(memory_id=memory_id)
    return {"deleted": memory_id}


# ── FastAPI app (REST + mounted MCP) ────────────────────────────────────

# Build the MCP sub-app once so we can also hoist its lifespan into FastAPI's.
# FastMCP's streamable-http app manages a task group that MUST be entered via
# its own lifespan; when mounted on a FastAPI app, the sub-app's lifespan is
# not triggered automatically, so POSTs fail with "Task group is not initialized".
mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load Mem0 (bge-m3 download is baked in the image, so this is fast).
    memory_backend.load()
    # Enter the MCP sub-app's lifespan so its task group is set up.
    async with mcp_app.router.lifespan_context(mcp_app):
        yield


app = FastAPI(title="memory-mcp", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health():
    if memory_backend.is_ready():
        return JSONResponse({"status": "ok", "pending_writes": memory_backend.pending_writes()})
    return JSONResponse({"status": "loading"}, status_code=503)


class AddRequest(BaseModel):
    content: str
    user_id: str = Field(default=config.DEFAULT_USER_ID)
    metadata: dict | None = None


@app.post("/v1/memory")
def rest_add(req: AddRequest):
    memory_backend.enqueue_add(req.content, user_id=req.user_id, metadata=req.metadata)
    return {"queued": True, "user_id": req.user_id, "pending": memory_backend.pending_writes()}


@app.get("/v1/memory/search")
def rest_search(query: str, user_id: str = config.DEFAULT_USER_ID, limit: int = 5):
    if not memory_backend.is_ready():
        raise HTTPException(status_code=503, detail="backend not ready")
    return {"query": query, "user_id": user_id,
            "results": memory_backend.search(query=query, user_id=user_id, limit=limit)}


@app.get("/v1/memory")
def rest_list(user_id: str = config.DEFAULT_USER_ID, limit: int = 100):
    if not memory_backend.is_ready():
        raise HTTPException(status_code=503, detail="backend not ready")
    results = memory_backend.list_all(user_id=user_id, limit=limit)
    return {"user_id": user_id, "count": len(results), "results": results}


@app.delete("/v1/memory/{memory_id}")
def rest_delete(memory_id: str):
    memory_backend.delete(memory_id=memory_id)
    return {"deleted": memory_id}


# Mount the MCP streamable-http app at /mcp. Clients (LibreChat, mcp-proxy,
# signal-bot via MCPClient) connect here with streamable-http transport.
# Note: FastMCP serves its handler at the sub-app's internal /mcp route, so
# the full external path is /mcp/mcp.
app.mount("/mcp", mcp_app)
