from __future__ import annotations

import logging
import math
import os
import sys
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.tests.integration.test_brand_kits import (
    _delete_supabase_user,
    _signup_and_login,
)


SAMPLE_COUNT = 30
WARMUP_COUNT = 5


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def main() -> None:
    logging.getLogger("backend.app.routes.brands").setLevel(logging.WARNING)
    logging.getLogger("backend.app.routes.brand_kits").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    supabase_url = _required_env("SUPABASE_URL")
    supabase_key = _required_env("SUPABASE_SECRET_KEY")
    _required_env("DATABASE_URL")

    from backend.app.config import get_engine
    from backend.app.main import app

    user_id: str | None = None
    brand_id: str | None = None
    with httpx.Client(timeout=30.0) as supabase_client:
        try:
            user_id, access_token = _signup_and_login(
                supabase_client,
                supabase_url,
                supabase_key,
                f"brand-kit-benchmark-{uuid4().hex[:10]}@example.com",
            )
            headers = {"Authorization": f"Bearer {access_token}"}
            with TestClient(app) as client:
                created = client.post(
                    "/api/v1/brands",
                    headers=headers,
                    json={"name": "Benchmark Brand"},
                )
                created.raise_for_status()
                brand_id = created.json()["id"]
                path = f"/api/v1/brands/{brand_id}/kit"

                for index in range(WARMUP_COUNT):
                    client.get(path, headers=headers).raise_for_status()
                    client.put(
                        path,
                        headers=headers,
                        json={
                            "name": "Benchmark Brand",
                            "answers": {"tagline": f"Warmup {index}"},
                        },
                    ).raise_for_status()

                get_samples: list[float] = []
                put_samples: list[float] = []
                for index in range(SAMPLE_COUNT):
                    started = perf_counter()
                    client.get(path, headers=headers).raise_for_status()
                    get_samples.append((perf_counter() - started) * 1000)

                    started = perf_counter()
                    client.put(
                        path,
                        headers=headers,
                        json={
                            "name": "Benchmark Brand",
                            "answers": {"tagline": f"Sample {index}"},
                        },
                    ).raise_for_status()
                    put_samples.append((perf_counter() - started) * 1000)

            get_p95 = _p95(get_samples)
            put_p95 = _p95(put_samples)
            print(
                f"Brand Kit local p95 ({SAMPLE_COUNT} samples): "
                f"GET {get_p95:.2f}ms, PUT {put_p95:.2f}ms"
            )
            if get_p95 >= 500 or put_p95 >= 500:
                raise SystemExit("Brand Kit p95 exceeded the 500ms goal")
        finally:
            original_failure = sys.exc_info()[0] is not None
            cleanup_errors: list[Exception] = []
            if brand_id:
                try:
                    with get_engine().begin() as connection:
                        connection.execute(
                            text("DELETE FROM brands WHERE id = :brand_id"),
                            {"brand_id": brand_id},
                        )
                except Exception as exc:
                    cleanup_errors.append(exc)
            if user_id:
                try:
                    _delete_supabase_user(
                        supabase_client, supabase_url, supabase_key, user_id
                    )
                except Exception as exc:
                    cleanup_errors.append(exc)
            if cleanup_errors and not original_failure:
                raise cleanup_errors[0]


if __name__ == "__main__":
    main()
