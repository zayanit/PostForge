import asyncio
from contextlib import nullcontext
from uuid import uuid4

import pytest
from backend.app import worker
from backend.app.services.brand_storage import BrandStorageUnknownError
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


@pytest.fixture(autouse=True)
def guard(monkeypatch):
    monkeypatch.setattr(worker, "generation_asset_guard", lambda *_: nullcontext())


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

    monkeypatch.setattr(worker, "generation_asset_guard", busy_then_free)
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

    monkeypatch.setattr(worker, "generation_asset_guard", always_busy)
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
    import os
    import signal

    events = []

    class OneJobStore:
        def claim(self):
            events.append("claim")
            return {**job(), "lease_token": uuid4()}

        def heartbeat(self, _job):
            return True

    async def slow_job(_store, _storage, _job):
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.2)
        events.append("finished")

    monkeypatch.setattr(worker, "HEARTBEAT_FILE", tmp_path / "heartbeat")
    monkeypatch.setattr(worker, "assert_database_role_privileges", lambda: None)
    monkeypatch.setattr(worker, "get_generation_store", OneJobStore)
    monkeypatch.setattr(worker, "get_generation_storage", Storage)
    monkeypatch.setattr(worker, "process_job", slow_job)

    asyncio.run(asyncio.wait_for(worker.run_worker(), timeout=5))
    assert events == ["claim", "finished"]
