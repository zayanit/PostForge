import asyncio
import json
import signal
import time
from contextlib import nullcontext
from uuid import uuid4

import pytest
from backend.app import worker
from backend.app.services.brand_storage import BrandStorageUnknownError
from backend.app.services import generation_store
from backend.app.services.generation_store import GenerationConflict


class Store:
    engine = None
    active = True
    key = "secret"

    def __init__(self):
        self.results = []

    def usable(self, job):
        return self.active

    def credential(self, job):
        return self.key

    def begin_upload(self, job):
        return self.active

    def finish(self, job, **result):
        if not self.active:
            return False
        self.results.append(result)
        return True


class Storage:
    exists = False
    uploads = 0
    fail = False

    def path(self, brand, generation):
        return f"brands/{brand}/generations/{generation}.png"

    async def object_exists(self, path):
        return self.exists

    async def upload(self, path, data):
        self.uploads += 1
        if self.fail:
            raise BrandStorageUnknownError


# The worker takes the asset lock through generation_asset_guard_in_thread, which
# calls generation_store.generation_asset_guard; stub that to avoid a database.
@pytest.fixture(autouse=True)
def guard(monkeypatch):
    monkeypatch.setattr(
        generation_store, "generation_asset_guard", lambda *_: nullcontext()
    )


def job(recovery=False):
    return {"id": uuid4(), "brand_id": uuid4(), "recovery": recovery}


@pytest.mark.parametrize("exists", [True, False])
def test_recovery_reconciles_without_a_second_provider_call(exists):
    store, storage = Store(), Storage()
    storage.exists = exists

    async def provider(*_):
        pytest.fail("Recovery must never repeat paid provider calls")

    asyncio.run(worker.process_job(store, storage, job(True), provider))
    assert storage.uploads == 0
    assert bool(store.results[0].get("path")) is exists
    if not exists:
        assert store.results[0]["error"] == "GENERATION_INTERRUPTED"


def test_unknown_upload_is_left_for_reconciliation():
    store, storage = Store(), Storage()
    storage.fail = True

    async def provider(*_):
        return b"PNG", "request-id"

    asyncio.run(worker.process_job(store, storage, job(), provider))
    assert storage.uploads == 1
    assert not store.results


def test_deleted_brand_or_stale_lease_cannot_publish():
    store, storage = Store(), Storage()

    async def provider(*_):
        store.active = False
        return b"PNG", "request-id"

    asyncio.run(worker.process_job(store, storage, job(), provider))
    assert storage.uploads == 0
    assert not store.results


def test_revoked_key_prevents_provider_call():
    store, storage = Store(), Storage()
    store.key = None

    async def provider(*_):
        pytest.fail("Missing credentials must not reach provider")

    asyncio.run(worker.process_job(store, storage, job(), provider))
    assert store.results == [{"error": "OPENAI_KEY_REQUIRED"}]


def test_busy_asset_guard_is_awaited_instead_of_discarding_the_image(monkeypatch):
    store, storage = Store(), Storage()
    attempts = []

    def busy_then_free(*_):
        attempts.append(None)
        if len(attempts) < 3:
            raise GenerationConflict("GENERATION_ASSET_BUSY")
        return nullcontext()

    monkeypatch.setattr(generation_store, "generation_asset_guard", busy_then_free)
    monkeypatch.setattr(worker, "GUARD_RETRY_SECONDS", 0)

    async def provider(*_):
        return b"PNG", "request-id"

    asyncio.run(worker.process_job(store, storage, job(), provider))
    assert len(attempts) == 3
    assert storage.uploads == 1
    assert store.results[0]["path"]


def test_persistently_busy_asset_guard_leaves_job_for_reconciliation(monkeypatch):
    store, storage = Store(), Storage()

    def always_busy(*_):
        raise GenerationConflict("GENERATION_ASSET_BUSY")

    monkeypatch.setattr(generation_store, "generation_asset_guard", always_busy)
    monkeypatch.setattr(worker, "GUARD_ATTEMPTS", 3)
    monkeypatch.setattr(worker, "GUARD_RETRY_SECONDS", 0)

    async def provider(*_):
        return b"PNG", "request-id"

    asyncio.run(worker.process_job(store, storage, job(), provider))
    assert storage.uploads == 0
    assert not store.results


def test_liveness_heartbeat_does_not_depend_on_the_database(monkeypatch, tmp_path):
    heartbeat = tmp_path / "heartbeat"

    class UnreachableStore:
        def claim(self):
            raise OSError("database unavailable")

    monkeypatch.setattr(worker, "HEARTBEAT_FILE", heartbeat)
    monkeypatch.setattr(worker, "assert_database_role_privileges", lambda: None)
    monkeypatch.setattr(worker, "get_generation_store", UnreachableStore)
    monkeypatch.setattr(worker, "get_generation_storage", Storage)

    async def scenario():
        task = asyncio.create_task(worker.run_worker())
        await asyncio.sleep(0.1)
        written = heartbeat.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return written

    assert asyncio.run(scenario())
    assert not heartbeat.exists()


def test_sigterm_finishes_the_current_job_and_claims_no_more(monkeypatch, tmp_path):
    events = []

    class OneJobStore:
        def claim(self):
            events.append("claim")
            return {**job(), "lease_token": uuid4()}

        def heartbeat(self, _job):
            return True

    async def slow_job(_store, _storage, _job):
        # raise_signal runs the registered handler on every platform; os.kill with
        # SIGTERM would terminate the process outright on Windows.
        signal.raise_signal(signal.SIGTERM)
        await asyncio.sleep(0.2)
        events.append("finished")
        return {"outcome": "succeeded"}

    monkeypatch.setattr(worker, "HEARTBEAT_FILE", tmp_path / "heartbeat")
    monkeypatch.setattr(worker, "assert_database_role_privileges", lambda: None)
    monkeypatch.setattr(worker, "get_generation_store", OneJobStore)
    monkeypatch.setattr(worker, "get_generation_storage", Storage)
    monkeypatch.setattr(worker, "process_job", slow_job)

    asyncio.run(asyncio.wait_for(worker.run_worker(), timeout=5))
    assert events == ["claim", "finished"]


def _run_one(monkeypatch, tmp_path, outcome_or_error):
    """Run the worker loop for exactly one claimed job, then stop."""
    import logging

    from backend.app.log import JsonLogFormatter

    claimed = {**job(), "lease_token": uuid4()}

    class OneJobStore:
        calls = 0

        def claim(self):
            self.calls += 1
            if self.calls > 1:
                # Stop the worker the way the container does.
                signal.raise_signal(signal.SIGTERM)
                return None
            return claimed

        def heartbeat(self, _job):
            return True

    async def fake_process(*_):
        if isinstance(outcome_or_error, Exception):
            raise outcome_or_error
        return outcome_or_error

    records = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(JsonLogFormatter().format(record))
    worker.logger.addHandler(handler)
    monkeypatch.setattr(worker, "HEARTBEAT_FILE", tmp_path / "heartbeat")
    monkeypatch.setattr(worker, "assert_database_role_privileges", lambda: None)
    monkeypatch.setattr(worker, "get_generation_store", OneJobStore)
    monkeypatch.setattr(worker, "get_generation_storage", Storage)
    monkeypatch.setattr(worker, "process_job", fake_process)
    monkeypatch.setattr(worker.asyncio, "sleep", _fast_sleep)
    try:
        asyncio.run(asyncio.wait_for(worker.run_worker(), timeout=5))
    finally:
        worker.logger.removeHandler(handler)
    return claimed, [json.loads(line) for line in records]


_real_sleep = asyncio.sleep


async def _fast_sleep(_seconds):
    await _real_sleep(0)


def test_job_outcome_is_logged_with_identifiers_and_code(monkeypatch, tmp_path):
    claimed, logs = _run_one(
        monkeypatch, tmp_path, {"outcome": "failed", "code": "PROVIDER_TIMEOUT"}
    )
    finished = next(e for e in logs if e.get("event") == "generation.job_finished")
    assert finished["level"] == "WARNING"
    assert finished["outcome"] == "failed"
    assert finished["code"] == "PROVIDER_TIMEOUT"
    assert finished["generation_id"] == str(claimed["id"])
    assert finished["brand_id"] == str(claimed["brand_id"])
    assert isinstance(finished["duration_ms"], int)


def test_unexpected_error_logs_class_name_but_never_its_text(monkeypatch, tmp_path):
    claimed, logs = _run_one(
        monkeypatch, tmp_path, RuntimeError("sk-secret-key and a signed URL")
    )
    error = next(e for e in logs if e.get("event") == "generation.worker_error")
    assert error["error_type"] == "RuntimeError"
    assert error["generation_id"] == str(claimed["id"])
    assert "sk-secret" not in json.dumps(logs)


def test_blocked_database_call_does_not_stall_liveness(monkeypatch, tmp_path):
    import threading

    heartbeat = tmp_path / "heartbeat"
    release = threading.Event()

    class StuckStore:
        def claim(self):
            # On the event loop this would block liveness until released.
            release.wait(timeout=5)
            return None

    monkeypatch.setattr(worker, "HEARTBEAT_FILE", heartbeat)
    monkeypatch.setattr(worker, "HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(worker, "assert_database_role_privileges", lambda: None)
    monkeypatch.setattr(worker, "get_generation_store", StuckStore)
    monkeypatch.setattr(worker, "get_generation_storage", Storage)

    async def scenario():
        started = time.monotonic()
        task = asyncio.create_task(worker.run_worker())
        await asyncio.sleep(0.05)
        first = heartbeat.read_text() if heartbeat.exists() else None
        await asyncio.sleep(0.2)
        refreshed = heartbeat.exists() and heartbeat.read_text() != first
        # If claim() blocked the loop, these sleeps could only resume after the
        # 5-second release timeout.
        elapsed = time.monotonic() - started
        release.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return refreshed, elapsed

    refreshed, elapsed = asyncio.run(scenario())
    assert refreshed
    assert elapsed < 2
