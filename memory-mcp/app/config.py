"""Centralized config for memory-mcp.

All values come from env vars so the service is fully declarative from docker-compose.
"""

import os

# The LLM that Mem0 uses for fact extraction, dedup decisions, and summarization.
# Points at llama-swap (serving qwen) on the host. OpenAI-compatible endpoint.
LLM_BASE_URL = os.getenv("MEMORY_LLM_BASE_URL", "http://host.docker.internal:8080/v1")
LLM_MODEL = os.getenv("MEMORY_LLM_MODEL", "qwen")
LLM_API_KEY = os.getenv("MEMORY_LLM_API_KEY", "sk-no-key-required")

# Local embedder — bge-m3 runs inside this container on CPU via sentence-transformers.
EMBED_MODEL = os.getenv("MEMORY_EMBED_MODEL", "BAAI/bge-m3")
EMBED_DIMS = int(os.getenv("MEMORY_EMBED_DIMS", "1024"))

# Qdrant — sibling container on the same Docker network.
QDRANT_HOST = os.getenv("MEMORY_QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("MEMORY_QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("MEMORY_QDRANT_COLLECTION", "memory")

# Default user scope when the caller doesn't supply one.
# A single-user stack can leave this as "kacper"; multi-user deployments
# will want the client to always pass user_id explicitly.
DEFAULT_USER_ID = os.getenv("MEMORY_DEFAULT_USER_ID", "default")
