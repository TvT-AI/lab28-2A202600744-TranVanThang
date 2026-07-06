"""Publish sample documents to the Kafka ingestion topic."""

from __future__ import annotations

import json
import os
import time
from typing import Iterable

from kafka import KafkaProducer

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")


def ingest_data(records: Iterable[dict]) -> int:
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        acks="all",
        retries=5,
    )
    count = 0
    try:
        for record in records:
            producer.send("data.raw", value=record).get(timeout=30)
            print(f"Sent: {record['id']}")
            count += 1
        producer.flush(timeout=30)
    finally:
        producer.close()
    return count


if __name__ == "__main__":
    now = time.time()
    sample_data = [
        {"id": "doc_001", "text": "AI platform integration test", "timestamp": now},
        {"id": "doc_002", "text": "Kafka to Prefect data pipeline", "timestamp": now},
        {"id": "doc_003", "text": "Reliable model serving with observability", "timestamp": now},
    ]
    sent = ingest_data(sample_data)
    print(f"Integration 1 OK: {sent} record(s) sent to Kafka")
