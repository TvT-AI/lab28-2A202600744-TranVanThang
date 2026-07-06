"""Prefect flow connecting Kafka, the data lake, Redis, and Qdrant."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import redis
import requests
from kafka import KafkaConsumer
from prefect import flow, get_run_logger, task

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
DELTA_PATH = Path(os.getenv("DELTA_PATH", "/opt/delta-lake/raw"))
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/")
EMBED_URL = os.getenv("EMBED_URL", "http://embedding-service:8002").rstrip("/")
VECTOR_SIZE = 384


@task(retries=3, retry_delay_seconds=5)
def consume_and_process() -> list[dict]:
    """Consume only records not yet processed by this pipeline."""
    logger = get_run_logger()
    consumer = KafkaConsumer(
        "data.raw",
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id="prefect-kafka-to-delta-v1",
        enable_auto_commit=True,
        auto_offset_reset="earliest",
        consumer_timeout_ms=10_000,
        value_deserializer=lambda message: json.loads(message.decode("utf-8")),
    )
    try:
        records = [message.value for message in consumer]
    finally:
        consumer.close()

    logger.info("Consumed %s record(s) from Kafka", len(records))
    return records


@task(retries=2, retry_delay_seconds=3)
def save_to_delta(records: list[dict]) -> str | None:
    """Persist the batch as Parquet in the mounted data-lake directory."""
    if not records:
        return None

    DELTA_PATH.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    output_path = DELTA_PATH / f"batch_{timestamp}.parquet"
    pd.DataFrame(records).to_parquet(output_path, index=False)
    get_run_logger().info("Saved %s record(s) to %s", len(records), output_path)
    return str(output_path)


@task(retries=3, retry_delay_seconds=3)
def publish_features(records: list[dict]) -> int:
    """Materialize online features in the Redis-backed feature store."""
    if not records:
        return 0

    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    pipeline = client.pipeline()
    for record in records:
        payload = {
            "text": record["text"],
            "timestamp": record.get("timestamp"),
            "processed": True,
        }
        pipeline.set(f"feature:{record['id']}", json.dumps(payload))
    pipeline.execute()
    get_run_logger().info("Published %s feature record(s) to Redis", len(records))
    return len(records)


@task(retries=3, retry_delay_seconds=5)
def embed_and_index(records: list[dict]) -> int:
    """Create embeddings and upsert the records into Qdrant."""
    if not records:
        return 0

    embed_response = requests.post(
        f"{EMBED_URL}/embed",
        json={"texts": [record["text"] for record in records]},
        timeout=60,
    )
    embed_response.raise_for_status()
    embeddings = embed_response.json()["embeddings"]

    collection_response = requests.put(
        f"{QDRANT_URL}/collections/documents",
        json={"vectors": {"size": VECTOR_SIZE, "distance": "Cosine"}},
        timeout=15,
    )
    if collection_response.status_code not in (200, 201, 409):
        collection_response.raise_for_status()

    points = []
    for record, embedding in zip(records, embeddings, strict=True):
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"lab28:{record['id']}"))
        points.append({"id": point_id, "vector": embedding, "payload": record})

    upsert_response = requests.put(
        f"{QDRANT_URL}/collections/documents/points",
        params={"wait": "true"},
        json={"points": points},
        timeout=30,
    )
    upsert_response.raise_for_status()
    get_run_logger().info("Indexed %s vector(s) in Qdrant", len(points))
    return len(points)


@flow(name="Kafka to Delta Pipeline", log_prints=True)
def kafka_to_delta_flow() -> dict[str, object]:
    """Run the event-driven batch through every local data integration."""
    records = consume_and_process()
    if not records:
        return {"records": 0, "status": "no-new-data"}

    delta_file = save_to_delta(records)
    feature_count = publish_features(records)
    vector_count = embed_and_index(records)
    return {
        "records": len(records),
        "delta_file": delta_file,
        "features": feature_count,
        "vectors": vector_count,
        "status": "completed",
    }


if __name__ == "__main__":
    kafka_to_delta_flow()
