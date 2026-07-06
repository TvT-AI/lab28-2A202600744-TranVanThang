"""Verify local metrics/dashboards and optional LangSmith tracing."""

from __future__ import annotations

import os
from pathlib import Path

import requests


def local_env(name: str, default: str = "") -> str:
    if value := os.getenv(name):
        return value
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return default


def check_prometheus() -> None:
    response = requests.get(
        "http://localhost:9090/api/v1/query",
        params={"query": 'up{job="api-gateway"}'},
        timeout=10,
    )
    response.raise_for_status()
    result = response.json()["data"]["result"]
    assert result and result[0]["value"][1] == "1", "API Gateway is not being scraped"
    print("Integration 9 OK: Prometheus is scraping API Gateway")


def check_grafana() -> None:
    response = requests.get("http://localhost:3000/api/health", auth=("admin", "admin"), timeout=10)
    response.raise_for_status()
    print("Grafana OK: provisioned dashboard is accessible")


def check_langsmith() -> None:
    api_key = local_env("LANGCHAIN_API_KEY")
    if not api_key:
        print("Integration 10 SKIP: set LANGCHAIN_API_KEY to verify remote LangSmith traces")
        return
    from langsmith import Client

    project = local_env("LANGCHAIN_PROJECT", "lab28-platform")
    runs = list(Client(api_key=api_key).list_runs(project_name=project, limit=1))
    assert runs, f"No LangSmith runs found in {project}"
    print("Integration 10 OK: LangSmith trace is visible")


if __name__ == "__main__":
    check_prometheus()
    check_grafana()
    check_langsmith()
