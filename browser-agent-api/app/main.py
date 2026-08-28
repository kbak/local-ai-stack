"""Task-oriented browser agent API backed by Browser Use and a local LLM."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from browser_use import Agent, Browser, ChatOpenAI
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl

log = logging.getLogger("browser-agent-api")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://llama.kacper.me/v1").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "vllm")
LLM_MODEL = os.getenv("LLM_MODEL", "")
API_TOKEN = os.getenv("BROWSER_AGENT_API_TOKEN", "")
DEFAULT_MAX_STEPS = int(os.getenv("BROWSER_AGENT_MAX_STEPS", "20"))
MAX_CONCURRENT_TASKS = int(os.getenv("BROWSER_AGENT_MAX_CONCURRENT_TASKS", "1"))
TASK_RETENTION_SECONDS = int(os.getenv("BROWSER_AGENT_TASK_RETENTION_SECONDS", "86400"))
USE_VISION_DEFAULT = os.getenv("BROWSER_AGENT_USE_VISION", "false").lower() == "true"
BROWSER_CDP_URL = os.getenv("BROWSER_AGENT_CDP_URL", "").strip()
STEEL_BASE_URL = os.getenv("BROWSER_AGENT_STEEL_BASE_URL", "").rstrip("/")
STEEL_PUBLIC_URL = os.getenv("BROWSER_AGENT_STEEL_PUBLIC_URL", STEEL_BASE_URL).rstrip("/")
STEEL_API_KEY = os.getenv("BROWSER_AGENT_STEEL_API_KEY", "")
STEEL_PROXY_URL = os.getenv("BROWSER_AGENT_STEEL_PROXY_URL", "")
STEEL_SOLVE_CAPTCHA = os.getenv("BROWSER_AGENT_STEEL_SOLVE_CAPTCHA", "false").lower() == "true"
STEEL_RESOLVE_WS_HOST = os.getenv("BROWSER_AGENT_STEEL_RESOLVE_WS_HOST", "true").lower() == "true"
TASK_TIMEOUT_SECONDS = int(os.getenv("BROWSER_AGENT_TASK_TIMEOUT_SECONDS", "600"))

app = FastAPI(title="browser-agent-api", version="0.1.0")
task_slots = threading.BoundedSemaphore(MAX_CONCURRENT_TASKS)


class TaskRequest(BaseModel):
    task: str = Field(min_length=1, max_length=20_000)
    start_url: HttpUrl | None = None
    allowed_domains: list[str] = Field(default_factory=list, max_length=100)
    max_steps: int = Field(default=DEFAULT_MAX_STEPS, ge=1, le=100)
    use_vision: bool = USE_VISION_DEFAULT
    output_schema: dict[str, Any] | None = None


class TaskAccepted(BaseModel):
    id: str
    status: Literal["queued"]


class TaskView(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "failed"]
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    model: str | None = None
    result: Any = None
    final_text: str | None = None
    steps: int | None = None
    duration_seconds: float | None = None
    urls: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


@dataclass
class TaskRecord:
    view: TaskView
    request: TaskRequest = field(repr=False)


tasks: dict[str, TaskRecord] = {}


@dataclass
class BrowserResource:
    browser: Browser
    steel_session_id: str | None = None


def steel_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if STEEL_API_KEY:
        headers["steel-api-key"] = STEEL_API_KEY
    return headers


def rewrite_steel_websocket_url(websocket_url: str) -> str:
    """Replace Steel's advertised bind address with its caller-visible address."""
    if not STEEL_PUBLIC_URL:
        return websocket_url
    advertised = urlsplit(websocket_url)
    public = urlsplit(STEEL_PUBLIC_URL)
    scheme = "wss" if public.scheme == "https" else "ws"
    netloc = public.netloc
    # Steel proxies the incoming Host header to Chrome's debugging socket.
    # Chromium rejects non-IP/non-localhost Host values with HTTP 500, so a
    # Docker service name must be resolved before Browser Use opens the socket.
    if STEEL_RESOLVE_WS_HOST and public.hostname and public.hostname not in {"localhost", "127.0.0.1"}:
        resolved_host = socket.gethostbyname(public.hostname)
        netloc = f"{resolved_host}:{public.port}" if public.port else resolved_host
    return urlunsplit((scheme, netloc, advertised.path or "/", advertised.query, ""))


async def create_browser(request: TaskRequest) -> BrowserResource:
    common: dict[str, Any] = {
        "allowed_domains": request.allowed_domains or None,
        "downloads_path": "/data/downloads",
    }
    if STEEL_BASE_URL:
        payload: dict[str, Any] = {
            "blockAds": True,
            "solveCaptcha": STEEL_SOLVE_CAPTCHA,
            "dimensions": {"width": 1920, "height": 1080},
        }
        if STEEL_PROXY_URL:
            payload["proxyUrl"] = STEEL_PROXY_URL
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{STEEL_BASE_URL}/v1/sessions",
                headers=steel_headers(),
                json=payload,
            )
            response.raise_for_status()
        session = response.json()
        session_id = session.get("id")
        websocket_url = session.get("websocketUrl")
        if not session_id or not websocket_url:
            raise RuntimeError("Steel session response omitted id or websocketUrl")
        common["cdp_url"] = rewrite_steel_websocket_url(websocket_url)
        return BrowserResource(browser=Browser(**common), steel_session_id=session_id)
    if BROWSER_CDP_URL:
        common["cdp_url"] = BROWSER_CDP_URL
    else:
        common.update(headless=True, chromium_sandbox=True)
    return BrowserResource(browser=Browser(**common))


async def release_steel_session(session_id: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{STEEL_BASE_URL}/v1/sessions/{session_id}/release",
                headers=steel_headers(),
            )
            response.raise_for_status()
    except Exception:
        log.exception("failed to release Steel session %s", session_id)


async def require_token(authorization: str | None = Header(default=None)) -> None:
    if not API_TOKEN:
        return
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")


async def resolve_model() -> str:
    if LLM_MODEL:
        return LLM_MODEL
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{LLM_BASE_URL}/models", headers={"Authorization": f"Bearer {LLM_API_KEY}"})
        response.raise_for_status()
    model_ids = [item["id"] for item in response.json().get("data", [])]
    preferred = [model for model in model_ids if "qwen3.8-27B" in model]
    if preferred:
        return preferred[0]
    chat_models = [model for model in model_ids if "qwen" in model.lower() and "reranker" not in model.lower()]
    if not chat_models:
        raise RuntimeError("no Qwen chat model is available from the configured LLM endpoint")
    return chat_models[-1]


def browser_output_schema(requested: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
    """Browser Use 0.13 requires an object root; wrap requested root arrays."""
    if requested and requested.get("type") == "array":
        return {
            "type": "object",
            "properties": {"result": requested},
            "required": ["result"],
        }, True
    return requested, False


def build_task_prompt(request: TaskRequest, effective_schema: dict[str, Any] | None) -> str:
    parts = [request.task]
    if STEEL_BASE_URL:
        parts.append(
            "Browser operation guidance: if a security verification page is actively checking the browser, "
            "wait in 30-second intervals for up to 90 seconds before reloading or concluding that access is blocked."
        )
    if request.start_url:
        parts.append(f"Start at this URL: {request.start_url}")
    if effective_schema:
        parts.append(
            "Use the browser extract action with the schema below, then return that validated JSON unchanged in your final answer. "
            "Do not hand-format or rewrite it.\n"
            + json.dumps(effective_schema, separators=(",", ":"))
        )
    return "\n\n".join(parts)


def parse_result(final_text: str | None, schema_requested: bool, unwrap_result: bool) -> Any:
    if not final_text or not schema_requested:
        return final_text
    candidate = final_text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(candidate)
        return parsed.get("result") if unwrap_result and isinstance(parsed, dict) else parsed
    except json.JSONDecodeError:
        return None


async def run_task(task_id: str) -> None:
    record = tasks[task_id]
    view = record.view
    request = record.request
    with task_slots:
        view.status = "running"
        view.started_at = time.time()
        browser_resource: BrowserResource | None = None
        try:
            model = await resolve_model()
            view.model = model
            effective_schema, unwrap_result = browser_output_schema(request.output_schema)
            llm = ChatOpenAI(model=model, base_url=LLM_BASE_URL, api_key=LLM_API_KEY, temperature=0.1)
            browser_resource = await create_browser(request)
            agent = Agent(
                task=build_task_prompt(request, effective_schema),
                llm=llm,
                browser=browser_resource.browser,
                use_vision=request.use_vision,
                extraction_schema=effective_schema,
                use_judge=False,
                calculate_cost=False,
                enable_signal_handler=False,
                source="browser-agent-api",
            )
            history = await asyncio.wait_for(
                agent.run(max_steps=request.max_steps),
                timeout=TASK_TIMEOUT_SECONDS,
            )
            view.final_text = history.final_result()
            view.result = parse_result(view.final_text, request.output_schema is not None, unwrap_result)
            view.steps = history.number_of_steps()
            view.duration_seconds = history.total_duration_seconds()
            view.urls = history.urls()
            view.errors = [str(error) for error in history.errors() if error]
            view.status = "completed" if view.final_text is not None else "failed"
        except Exception as exc:
            log.exception("browser task %s failed", task_id)
            view.errors.append(f"{type(exc).__name__}: {exc}")
            view.status = "failed"
        finally:
            if browser_resource is not None:
                try:
                    await browser_resource.browser.stop()
                except Exception:
                    log.exception("failed to stop browser for task %s", task_id)
                if browser_resource.steel_session_id:
                    await release_steel_session(browser_resource.steel_session_id)
            view.finished_at = time.time()
            if view.duration_seconds is None and view.started_at:
                view.duration_seconds = view.finished_at - view.started_at


def run_task_worker(task_id: str) -> None:
    """Run Browser Use on a dedicated thread so its sync CDP work cannot stall FastAPI."""
    asyncio.run(run_task(task_id))


def prune_old_tasks() -> None:
    cutoff = time.time() - TASK_RETENTION_SECONDS
    expired = [task_id for task_id, record in tasks.items() if record.view.finished_at and record.view.finished_at < cutoff]
    for task_id in expired:
        tasks.pop(task_id, None)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "llm_base_url": LLM_BASE_URL,
        "configured_model": LLM_MODEL or "auto",
        "browser_backend": "steel" if STEEL_BASE_URL else ("cdp" if BROWSER_CDP_URL else "local"),
    }


@app.post("/v1/tasks", response_model=TaskAccepted, status_code=status.HTTP_202_ACCEPTED)
async def create_task(
    request: TaskRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_token),
) -> TaskAccepted:
    prune_old_tasks()
    task_id = f"task_{uuid.uuid4().hex}"
    view = TaskView(id=task_id, status="queued", created_at=time.time())
    tasks[task_id] = TaskRecord(view=view, request=request)
    background_tasks.add_task(run_task_worker, task_id)
    return TaskAccepted(id=task_id, status="queued")


@app.get("/v1/tasks/{task_id}", response_model=TaskView)
async def get_task(task_id: str, _: None = Depends(require_token)) -> TaskView:
    record = tasks.get(task_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return record.view
