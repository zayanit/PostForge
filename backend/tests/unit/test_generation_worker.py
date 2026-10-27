import asyncio
from contextlib import nullcontext
from uuid import uuid4

import pytest
from backend.app import worker
from backend.app.services.brand_storage import BrandStorageUnknownError


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
