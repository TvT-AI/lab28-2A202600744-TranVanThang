"""Embed sample documents and index them in Qdrant without destructive resets."""

from __future__ import annotations

import os
import uuid

import requests

EMBED_URL = os.getenv("EMBED_NGROK_URL", os.getenv("EMBED_URL", "http://localhost:8002")).rstrip("/")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")
VECTOR_SIZE = 384


def ensure_collection() -> None:
    response = requests.put(
        f"{QDRANT_URL}/collections/documents",
        json={"vectors": {"size": VECTOR_SIZE, "distance": "Cosine"}},
        timeout=15,
    )
    if response.status_code not in (200, 201, 409):
        response.raise_for_status()


def embed_and_store(records: list[dict]) -> int:
    response = requests.post(
        f"{EMBED_URL}/embed",
        json={"texts": [record["text"] for record in records]},
        timeout=60,
    )
    response.raise_for_status()
    embeddings = response.json()["embeddings"]
    ensure_collection()

    points = [
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"lab28:{record['id']}")),
            "vector": embedding,
            "payload": record,
        }
        for record, embedding in zip(records, embeddings, strict=True)
    ]
    upsert = requests.put(
        f"{QDRANT_URL}/collections/documents/points",
        params={"wait": "true"},
        json={"points": points},
        timeout=30,
    )
    upsert.raise_for_status()
    print(f"Integration 5 OK: {len(points)} vector(s) stored in Qdrant")
    return len(points)


if __name__ == "__main__":
    embed_and_store(
        [
            {"id": "doc_001", "text": "AI platform integration test"},
            {"id": "doc_002", "text": "Kafka to Prefect data pipeline"},
        ]
    )
