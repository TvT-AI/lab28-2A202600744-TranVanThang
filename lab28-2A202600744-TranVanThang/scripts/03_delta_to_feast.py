"""Materialize Parquet records into the Redis online feature store."""

from __future__ import annotations

import glob
import json
import os

import pandas as pd
import redis

DELTA_GLOB = os.getenv("DELTA_GLOB", "delta-lake/raw/*.parquet")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def load_from_delta_and_push_feast() -> int:
    files = glob.glob(DELTA_GLOB)
    if not files:
        raise RuntimeError("No Parquet files found. Run the Prefect pipeline first.")

    dataframe = pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)
    dataframe = dataframe.drop_duplicates(subset=["id"], keep="last")
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    pipeline = client.pipeline()

    for row in dataframe.to_dict(orient="records"):
        pipeline.set(
            f"feature:{row['id']}",
            json.dumps(
                {
                    "text": row["text"],
                    "timestamp": row.get("timestamp"),
                    "processed": True,
                }
            ),
        )
    pipeline.execute()
    print(f"Integration 3+4 OK: {len(dataframe)} feature(s) stored in Redis")
    return len(dataframe)


if __name__ == "__main__":
    load_from_delta_and_push_feast()
