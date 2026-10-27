"""Run with python -m backend.app.worker (or python -m app.worker in the container)."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import tempfile
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from .config import assert_database_role_privileges
from .services.brand_storage import BrandStorageError
from .services.generation_storage import get_generation_storage
from .services.generation_store import (
    GenerationConflict,
    generation_asset_guard,
    get_generation_store,
)
from .services.image_generation import GenerationFailure, generate_openai

logger = logging.getLogger(__name__)
HEARTBEAT_FILE = Path(
    os.getenv(
        "GENERATION_WORKER_HEARTBEAT",
        str(Path(tempfile.gettempdir()) / "postforge-worker-heartbeat"),
    )
)


async def process_job(store, storage, job, generate=generate_openai):
    path = storage.path(job["brand_id"], job["id"])
    if job["recovery"]:
        with generation_asset_guard(store.engine, job["brand_id"]):
            if not store.usable(job):
                return
            # Respect a previous upload's uncertainty window even if its worker
            # lease expired early. Do not turn an in-flight write into a failed row.
            if job.get("upload_fence_until") is not None:
                if job["upload_fence_until"] > datetime.now(UTC):
                    return
            if await storage.object_exists(path):
                store.finish(job, path=path)
            else:
                store.finish(job, error="GENERATION_INTERRUPTED")
        return
    error = None
    try:
        key = store.credential(job)
        if not key:
            raise GenerationFailure("OPENAI_KEY_REQUIRED")
        if not store.usable(job):
            return
        data, request_id = await generate(job, key)
        key = None
        with generation_asset_guard(store.engine, job["brand_id"]):
            if not store.usable(job) or not store.begin_upload(job):
                return
            # An uncertain upload remains processing for lease-based reconciliation.
            await storage.upload(path, data)
            store.finish(job, path=path, provider_request_id=request_id)
    except GenerationFailure as exc:
        error = exc.code
    except (BrandStorageError, GenerationConflict):
        return
    if error:
        store.finish(job, error=error)


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

    async def heartbeat(job):
        while True:
            HEARTBEAT_FILE.write_text(str(time.time()))
            if job is not None and not store.heartbeat(job):
                return
            await asyncio.sleep(15)

    while not stop.is_set():
        job = None
        pulse = None
        try:
            job = store.claim()
            pulse = asyncio.create_task(heartbeat(job))
            if job:
                await process_job(store, storage, job)
            else:
                await asyncio.sleep(2)
        except Exception:
            # Exceptions may contain credentials, prompts, SQL, or signed URLs.
            logger.error("generation.worker_error")
            await asyncio.sleep(2)
        finally:
            if pulse:
                pulse.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await pulse
    HEARTBEAT_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    # Fixed log text also keeps unexpected SQL/storage exceptions out of logs.
    logging.basicConfig(
        format='{"event":"generation.worker_error","level":"%(levelname)s"}'
    )
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.error("generation.worker_error")
        raise SystemExit(1) from None
