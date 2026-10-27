"""Run with python -m backend.app.worker (or python -m app.worker in the container)."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import tempfile
import time
from contextlib import ExitStack, asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

from .config import assert_database_role_privileges
from .log import configure_logging
from .services.brand_storage import BrandStorageError
from .services.generation_storage import get_generation_storage
from .services.generation_store import (
    GenerationConflict,
    generation_asset_guard,
    get_generation_store,
)
from .services.image_generation import GenerationFailure, generate_openai

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 15
# Wait up to a minute for a brand's asset lock (held briefly by user deletions,
# other workers' uploads, or brand cleanup) instead of discarding a paid image.
GUARD_ATTEMPTS = 120
GUARD_RETRY_SECONDS = 0.5
HEARTBEAT_FILE = Path(
    os.getenv(
        "GENERATION_WORKER_HEARTBEAT",
        str(Path(tempfile.gettempdir()) / "postforge-worker-heartbeat"),
    )
)


@asynccontextmanager
async def wait_for_asset_guard(engine, brand_id):
    for attempt in range(GUARD_ATTEMPTS):
        with ExitStack() as stack:
            try:
                stack.enter_context(generation_asset_guard(engine, brand_id))
            except GenerationConflict:
                if attempt + 1 == GUARD_ATTEMPTS:
                    raise
                await asyncio.sleep(GUARD_RETRY_SECONDS)
                continue
            yield
            return


async def process_job(store, storage, job, generate=generate_openai) -> dict:
    """Process one claimed job and describe what happened, for logging."""
    path = storage.path(job["brand_id"], job["id"])
    if job["recovery"]:
        async with wait_for_asset_guard(store.engine, job["brand_id"]):
            if not store.usable(job):
                return {"outcome": "lease_lost"}
            # Respect a previous upload's uncertainty window even if its worker
            # lease expired early. Do not turn an in-flight write into a failed row.
            if job.get("upload_fence_until") is not None:
                if job["upload_fence_until"] > datetime.now(UTC):
                    return {"outcome": "upload_pending"}
            if await storage.object_exists(path):
                published = store.finish(job, path=path)
                return {"outcome": "recovered" if published else "lease_lost"}
            if not store.finish(job, error="GENERATION_INTERRUPTED"):
                return {"outcome": "lease_lost"}
            return {"outcome": "failed", "code": "GENERATION_INTERRUPTED"}
    error = None
    try:
        key = store.credential(job)
        if not key:
            raise GenerationFailure("OPENAI_KEY_REQUIRED")
        if not store.usable(job):
            return {"outcome": "lease_lost"}
        data, request_id = await generate(job, key)
        key = None
        async with wait_for_asset_guard(store.engine, job["brand_id"]):
            if not store.usable(job) or not store.begin_upload(job):
                return {"outcome": "lease_lost"}
            # An uncertain upload remains processing for lease-based reconciliation.
            await storage.upload(path, data)
            if not store.finish(job, path=path, provider_request_id=request_id):
                return {"outcome": "lease_lost"}
            return {"outcome": "succeeded", "provider_request_id": request_id}
    except GenerationFailure as exc:
        error = exc.code
    except BrandStorageError:
        return {"outcome": "upload_uncertain"}
    except GenerationConflict:
        return {"outcome": "asset_busy"}
    if not store.finish(job, error=error):
        return {"outcome": "lease_lost"}
    return {"outcome": "failed", "code": error}


def _log(level, event, job=None, **fields):
    if job is not None:
        fields.update(
            generation_id=job["id"], brand_id=job["brand_id"], recovery=job["recovery"]
        )
    logger.log(level, event, extra={"event": event, **fields})


async def run_worker():
    assert_database_role_privileges()
    store, storage = get_generation_store(), get_generation_storage()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))

    # Process liveness is independent of the database so that a database outage
    # does not make the container unhealthy (see the healthcheck contract).
    async def liveness():
        while True:
            try:
                HEARTBEAT_FILE.write_text(str(time.time()))
            except OSError as exc:
                _log(
                    logging.ERROR,
                    "generation.heartbeat_write_failed",
                    error_type=type(exc).__name__,
                )
            await asyncio.sleep(HEARTBEAT_SECONDS)

    async def lease_heartbeat(job):
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                if not store.heartbeat(job):
                    return
            except Exception as exc:
                # A transient database error must not end lease renewal.
                _log(
                    logging.WARNING,
                    "generation.lease_renewal_failed",
                    job,
                    error_type=type(exc).__name__,
                )

    _log(logging.INFO, "generation.worker_started")
    alive = asyncio.create_task(liveness())
    try:
        while not stop.is_set():
            pulse = None
            job = None
            try:
                job = store.claim()
                if job:
                    pulse = asyncio.create_task(lease_heartbeat(job))
                    started = time.monotonic()
                    result = await process_job(store, storage, job)
                    _log(
                        logging.WARNING
                        if result["outcome"] == "failed"
                        else logging.INFO,
                        "generation.job_finished",
                        job,
                        duration_ms=round((time.monotonic() - started) * 1000),
                        **result,
                    )
                else:
                    await asyncio.sleep(2)
            except Exception as exc:
                # Log only the class name: exception text may contain credentials,
                # prompts, SQL, or signed URLs.
                _log(
                    logging.ERROR,
                    "generation.worker_error",
                    job,
                    error_type=type(exc).__name__,
                )
                await asyncio.sleep(2)
            finally:
                if pulse:
                    pulse.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await pulse
    finally:
        alive.cancel()
        with suppress(asyncio.CancelledError):
            await alive
        HEARTBEAT_FILE.unlink(missing_ok=True)
        _log(logging.INFO, "generation.worker_stopped")


if __name__ == "__main__":
    # The allowlist formatter keeps exception text out of logs.
    configure_logging()
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        _log(logging.ERROR, "generation.worker_fatal", error_type=type(exc).__name__)
        raise SystemExit(1) from None
