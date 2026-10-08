"""Centralized config for memory-mcp.

All values come from env vars so the service is fully declarative from docker-compose.
"""

import os

API_TOKEN = os.getenv("MEMORY_API_TOKEN", "")

# The LLM that Mem0 uses for fact extraction, dedup decisions, and summarization.
# Points at llama-swap on the host. OpenAI-compatible endpoint.
# MEMORY_LLM_MODEL is optional - if unset, memory_backend.load() resolves the
# largest non-coder model currently loaded in llama-swap (see stack_shared).
LLM_BASE_URL = os.getenv("MEMORY_LLM_BASE_URL", "http://host.docker.internal:8080/v1")
LLM_MODEL = os.getenv("MEMORY_LLM_MODEL")  # None = auto-resolve at load time
LLM_API_KEY = os.getenv("MEMORY_LLM_API_KEY", "sk-no-key-required")

# Local embedder - bge-m3 runs inside this container on CPU via sentence-transformers.
EMBED_MODEL = os.getenv("MEMORY_EMBED_MODEL", "BAAI/bge-m3")
EMBED_DIMS = int(os.getenv("MEMORY_EMBED_DIMS", "1024"))

# Qdrant - sibling container on the same Docker network.
QDRANT_HOST = os.getenv("MEMORY_QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("MEMORY_QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("MEMORY_QDRANT_COLLECTION", "memory")

# Default user scope when the caller doesn't supply one.
# A single-user stack can leave this as "default"; multi-user deployments
# will want the client to always pass user_id explicitly.
DEFAULT_USER_ID = os.getenv("MEMORY_DEFAULT_USER_ID", "default")

# Exact proxy hostnames/origins for MCP DNS rebinding protection.
ALLOWED_HOSTS = [value.strip() for value in os.getenv(
    "MEMORY_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,memory-mcp:8089,host.docker.internal:8089"
).split(",") if value.strip()]
ALLOWED_ORIGINS = [value.strip() for value in os.getenv(
    "MEMORY_ALLOWED_ORIGINS", "http://localhost:8089,http://127.0.0.1:8089"
).split(",") if value.strip()]
