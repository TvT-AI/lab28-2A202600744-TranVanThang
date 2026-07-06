"""Lightweight deterministic embedding fallback for the local demo stack."""

from __future__ import annotations

import hashlib
import math
import re

from fastapi import FastAPI
from pydantic import BaseModel, Field

VECTOR_SIZE = 384
TOKEN_PATTERN = re.compile(r"[\w'-]+", re.UNICODE)

app = FastAPI(title="Lab28 Embedding Service", version="1.0.0")


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=128)


def embed_text(text: str) -> list[float]:
    """Create a normalized feature-hashing embedding without model downloads."""
    vector = [0.0] * VECTOR_SIZE
    tokens = TOKEN_PATTERN.findall(text.lower())
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_SIZE
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return vector


@app.post("/embed")
def embed(request: EmbedRequest) -> dict[str, list[list[float]]]:
    return {"embeddings": [embed_text(text) for text in request.texts]}


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "vector_size": VECTOR_SIZE, "backend": "feature-hashing"}
