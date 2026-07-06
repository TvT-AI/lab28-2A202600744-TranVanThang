"""Executable production-readiness checklist for the local platform."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

import redis
import requests

results: dict[str, str] = {}


def check(name: str, function: Callable[[], None]) -> None:
    try:
        function()
        results[name] = "PASS"
        print(f"  [PASS] {name}")
    except Exception as exc:  # noqa: BLE001 - checklist must continue after failures
        results[name] = f"FAIL: {exc}"
        print(f"  [FAIL] {name}: {exc}")


def get_ok(url: str, **kwargs) -> None:
    response = requests.get(url, timeout=15, **kwargs)
    response.raise_for_status()


def check_collection() -> None:
    response = requests.get("http://localhost:6333/collections/documents", timeout=10)
    response.raise_for_status()
    assert response.json()["result"]["points_count"] > 0


def check_feature_store() -> None:
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    assert client.ping()
    assert client.scan_iter(match="feature:*")
    assert next(client.scan_iter(match="feature:*"), None), "No materialized features"


def check_kafka_topic() -> None:
    result = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "kafka",
            "kafka-topics", "--list", "--bootstrap-server", "localhost:29092",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert "data.raw" in result.stdout


def check_prefect_deployment() -> None:
    response = requests.post(
        "http://localhost:4200/api/deployments/filter",
        json={"limit": 100},
        timeout=15,
    )
    response.raise_for_status()
    assert any(item["name"] == "kafka-to-delta" for item in response.json())


def check_prometheus_target() -> None:
    response = requests.get(
        "http://localhost:9090/api/v1/query",
        params={"query": 'up{job="api-gateway"}'},
        timeout=10,
    )
    response.raise_for_status()
    result = response.json()["data"]["result"]
    assert result and result[0]["value"][1] == "1"


def check_alert_rules() -> None:
    response = requests.get("http://localhost:9090/api/v1/rules", timeout=10)
    response.raise_for_status()
    groups = response.json()["data"]["groups"]
    assert any(group["name"] == "lab28-platform" for group in groups)


checks = [
    ("API Gateway liveness", lambda: get_ok("http://localhost:8000/health")),
    ("API Gateway readiness", lambda: get_ok("http://localhost:8000/ready")),
    ("Metrics endpoint", lambda: get_ok("http://localhost:8000/metrics")),
    ("Prometheus healthy", lambda: get_ok("http://localhost:9090/-/healthy")),
    ("Prometheus scraping gateway", check_prometheus_target),
    ("Prometheus alert rules", check_alert_rules),
    ("Grafana healthy", lambda: get_ok("http://localhost:3000/api/health", auth=("admin", "admin"))),
    ("Prefect healthy", lambda: get_ok("http://localhost:4200/api/health")),
    ("Prefect deployment registered", check_prefect_deployment),
    ("MLflow healthy", lambda: get_ok("http://localhost:5000/health")),
    ("Embedding service healthy", lambda: get_ok("http://localhost:8002/health")),
    ("Qdrant collection populated", check_collection),
    ("Redis feature store populated", check_feature_store),
    ("Kafka topic exists", check_kafka_topic),
]

if __name__ == "__main__":
    print("\n=== LAB28 PRODUCTION READINESS ===")
    for check_name, check_function in checks:
        check(check_name, check_function)

    passed = sum(value == "PASS" for value in results.values())
    total = len(results)
    score = passed / total * 100
    print("\n" + "=" * 48)
    print(f"Production Readiness Score: {passed}/{total} = {score:.0f}%")
    print(f"Target: >80% - Status: {'READY' if score > 80 else 'NOT READY'}")
