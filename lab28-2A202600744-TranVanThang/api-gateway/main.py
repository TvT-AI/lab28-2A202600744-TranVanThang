"""Resilient API gateway for retrieval-augmented vLLM inference."""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from langsmith import traceable
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field, field_validator

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("api-gateway")

VLLM_URL = os.environ["VLLM_URL"].rstrip("/")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4")
VLLM_TIMEOUT_SECONDS = float(os.getenv("VLLM_TIMEOUT_SECONDS", "120"))
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/")

UPSTREAM_ERRORS = Counter(
    "gateway_upstream_errors_total",
    "Number of failed upstream calls",
    ["upstream"],
)
INFERENCE_LATENCY = Histogram(
    "gateway_inference_duration_seconds",
    "End-to-end inference latency",
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120),
)

app = FastAPI(title="AI Platform API Gateway", version="1.0.0")
Instrumentator().instrument(app).expose(app)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4_000)
    embedding: list[float] = Field(default_factory=lambda: [0.0] * 384)

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, value: list[float]) -> list[float]:
        if len(value) != 384:
            raise ValueError("embedding must contain exactly 384 values")
        return value


class ChatResponse(BaseModel):
    answer: str
    latency_ms: float
    model: str
    request_id: str
    context_documents: int
    degraded: bool


async def search_context(embedding: list[float]) -> tuple[list[dict[str, Any]], bool]:
    """Search Qdrant, degrading to an empty context when it is unavailable."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{QDRANT_URL}/collections/documents/points/search",
                json={"vector": embedding, "limit": 3, "with_payload": True},
            )
        if response.status_code == 404:
            return [], True
        response.raise_for_status()
        return response.json().get("result", []), False
    except (httpx.HTTPError, ValueError) as exc:
        UPSTREAM_ERRORS.labels(upstream="qdrant").inc()
        logger.warning("Qdrant unavailable; continuing without context: %s", exc)
        return [], True


@traceable(name="vllm-chat-completion", run_type="llm")
async def call_vllm(prompt: str) -> dict[str, Any]:
    headers = {"ngrok-skip-browser-warning": "true"}
    try:
        async with httpx.AsyncClient(timeout=VLLM_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{VLLM_URL}/v1/chat/completions",
                headers=headers,
                json={
                    "model": VLLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 256,
                    "temperature": 0.2,
                },
            )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        UPSTREAM_ERRORS.labels(upstream="vllm").inc()
        logger.error("vLLM request failed: %s", exc)
        raise HTTPException(status_code=503, detail="vLLM service is unavailable") from exc


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    logger.info("request_id=%s method=%s path=%s status=%s", request_id, request.method, request.url.path, response.status_code)
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": request.state.request_id},
    )


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    start = time.perf_counter()
    context, degraded = await search_context(body.embedding)
    context_payload = [item.get("payload", item) for item in context]
    prompt = f"Context: {context_payload}\n\nQuery: {body.query}"

    with INFERENCE_LATENCY.time():
        result = await call_vllm(prompt)

    latency_ms = (time.perf_counter() - start) * 1_000
    answer = result["choices"][0]["message"]["content"]
    return ChatResponse(
        answer=answer,
        latency_ms=round(latency_ms, 2),
        model=result.get("model", VLLM_MODEL),
        request_id=request.state.request_id,
        context_documents=len(context),
        degraded=degraded,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def readiness() -> dict[str, object]:
    checks: dict[str, bool] = {}
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            checks["qdrant"] = (await client.get(f"{QDRANT_URL}/healthz")).is_success
        except httpx.HTTPError:
            checks["qdrant"] = False
        try:
            checks["vllm"] = (
                await client.get(
                    f"{VLLM_URL}/health",
                    headers={"ngrok-skip-browser-warning": "true"},
                )
            ).is_success
        except httpx.HTTPError:
            checks["vllm"] = False

    if not all(checks.values()):
        raise HTTPException(status_code=503, detail={"status": "not-ready", "checks": checks})
    return {"status": "ready", "checks": checks}
