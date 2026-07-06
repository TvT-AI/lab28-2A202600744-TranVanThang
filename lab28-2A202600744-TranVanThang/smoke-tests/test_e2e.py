"""Five end-to-end journeys required by the Lab28 submission rubric."""

from __future__ import annotations

import json
import subprocess
import time
import uuid

import redis
import requests
from kafka import KafkaProducer

BASE_URL = "http://localhost:8000"


def test_1_happy_path_inference() -> None:
    health = requests.get(f"{BASE_URL}/health", timeout=5)
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    response = requests.post(
        f"{BASE_URL}/api/v1/chat",
        json={"query": "What is platform engineering?", "embedding": [0.1] * 384},
        timeout=150,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["answer"]) > 10
    assert data["latency_ms"] < 120_000
    assert data["request_id"]


def test_2_ingestion_pipeline_to_qdrant() -> None:
    document_id = f"smoke_{uuid.uuid4().hex[:10]}"
    producer = KafkaProducer(
        bootstrap_servers="localhost:9092",
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )
    try:
        producer.send(
            "data.raw",
            {"id": document_id, "text": "smoke test event-driven document", "timestamp": time.time()},
        ).get(timeout=30)
        producer.flush()
    finally:
        producer.close()

    result = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "prefect-worker",
            "python", "/opt/prefect/flows/kafka_to_delta.py",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    for _ in range(30):
        scroll = requests.post(
            "http://localhost:6333/collections/documents/points/scroll",
            json={
                "filter": {"must": [{"key": "id", "match": {"value": document_id}}]},
                "limit": 1,
                "with_payload": True,
            },
            timeout=10,
        )
        assert scroll.status_code == 200, scroll.text
        if scroll.json()["result"]["points"]:
            break
        time.sleep(2)
    else:
        raise AssertionError(f"Document {document_id} was not indexed in Qdrant")


def test_3_observability_journey() -> None:
    query = requests.get(
        "http://localhost:9090/api/v1/query",
        params={"query": 'up{job="api-gateway"}'},
        timeout=10,
    )
    assert query.status_code == 200
    result = query.json()["data"]["result"]
    assert result and result[0]["value"][1] == "1"

    dashboard = requests.get(
        "http://localhost:3000/api/dashboards/uid/lab28-platform",
        auth=("admin", "admin"),
        timeout=10,
    )
    assert dashboard.status_code == 200


def test_4_validation_and_failure_path() -> None:
    invalid = requests.post(f"{BASE_URL}/api/v1/chat", json={}, timeout=5)
    assert invalid.status_code == 422

    wrong_vector = requests.post(
        f"{BASE_URL}/api/v1/chat",
        json={"query": "test", "embedding": [0.1]},
        timeout=5,
    )
    assert wrong_vector.status_code == 422
    assert requests.get(f"{BASE_URL}/health", timeout=5).status_code == 200


def test_5_feature_store_journey() -> None:
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    keys = list(client.scan_iter(match="feature:*"))
    assert keys, "No features found; run the ingestion pipeline first"
    payload = json.loads(client.get(keys[0]))
    assert payload["processed"] is True
