"""Log vLLM serving metadata and create an MLflow model registry version."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import mlflow
from mlflow import MlflowClient

TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MODEL_NAME = "Qwen2.5-7B-Instruct-GPTQ-Int4"


def local_env(name: str, default: str = "") -> str:
    if value := os.getenv(name):
        return value
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return default


VLLM_URL = local_env("VLLM_NGROK_URL", "configured-at-runtime")


def register_model() -> str:
    mlflow.set_tracking_uri(TRACKING_URI)
    mlflow.set_experiment("lab28-integration")

    with mlflow.start_run(run_name="vllm-serving-v1") as run:
        mlflow.log_params(
            {
                "model": MODEL_NAME,
                "max_model_len": 2048,
                "serving_backend": "vLLM",
                "deployment": "Kaggle GPU via ngrok",
            }
        )
        mlflow.log_metric("gpu_memory_utilization", 0.90)
        mlflow.set_tags({"serving_url": VLLM_URL, "status": "production"})
        with tempfile.TemporaryDirectory() as directory:
            metadata_path = os.path.join(directory, "serving_metadata.json")
            with open(metadata_path, "w", encoding="utf-8") as file:
                json.dump({"model": MODEL_NAME, "serving_url": VLLM_URL}, file, indent=2)
            mlflow.log_artifact(metadata_path, artifact_path="model-metadata")

    client = MlflowClient(tracking_uri=TRACKING_URI)
    try:
        client.create_registered_model(MODEL_NAME)
    except mlflow.exceptions.MlflowException as exc:
        if "already exists" not in str(exc):
            raise

    versions = client.search_model_versions(f"name='{MODEL_NAME}'")
    if not any(version.run_id == run.info.run_id for version in versions):
        client.create_model_version(
            name=MODEL_NAME,
            source=f"runs:/{run.info.run_id}/model-metadata",
            run_id=run.info.run_id,
            description="External vLLM deployment metadata",
        )
    print(f"Integration 6+7 OK: run_id={run.info.run_id}")
    return run.info.run_id


if __name__ == "__main__":
    register_model()
