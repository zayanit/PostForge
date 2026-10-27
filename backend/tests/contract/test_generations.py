from datetime import UTC, datetime
from uuid import uuid4

import pytest
from backend.app.auth import CurrentUser, get_current_user
from backend.app.main import app
from backend.app.routes.generations import get_generation_storage, get_generation_store
from backend.app.services.generation_store import GenerationConflict
from fastapi.testclient import TestClient

BRAND = uuid4()
GENERATION = uuid4()
OWNER = str(uuid4())


def row():
    return dict(
        id=GENERATION,
        brand_id=BRAND,
        prompt="Product launch",
        platform_preset="instagram_post",
        width=1080,
        height=1080,
        status="pending",
        created_at=datetime.now(UTC),
        cleanup_required=False,
        image_path=None,
    )


class Store:
    value = None
    exception = None

    def __init__(self):
        self.calls = []

    def submit(self, owner, brand, payload, request):
        self.calls.append((owner, brand, payload, request))
        if self.exception:
            raise self.exception
        return self.value or row()

    def get(self, *_):
        if self.exception:
            raise self.exception
        return self.value or row()

    def list(self, *args):
        self.calls.append(args)
        if self.exception:
            raise self.exception
        return [self.value or row()], 1


class Storage:
    def __init__(self):
        self.signs = []

    async def sign(self, path):
        self.signs.append(path)
        return "https://storage.test/private?token=temporary"


@pytest.fixture
def client():
    store, storage = Store(), Storage()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(OWNER)
    app.dependency_overrides[get_generation_store] = lambda: store
    app.dependency_overrides[get_generation_storage] = lambda: storage
    with TestClient(app) as test_client:
        yield test_client, store, storage
    app.dependency_overrides.clear()


def test_submission_returns_202_without_context_credentials_or_internal_fields(client):
    api, store, _ = client
    response = api.post(
        f"/api/v1/brands/{BRAND}/generate",
        headers={"Idempotency-Key": str(uuid4())},
        json={"prompt": "Product launch", "platform_preset": "instagram_post"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert store.calls[0][0] == OWNER
    assert store.calls[0][1] == BRAND
    for name in (
        "context_snapshot",
        "lease_token",
        "provider_key_id",
        "request_hash",
        "image_path",
    ):
        assert name not in response.json()


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": "x", "platform_preset": "instagram_post"},
        {"prompt": "   ", "platform_preset": "instagram_post"},
        {"prompt": "x" * 4001, "platform_preset": "instagram_post"},
        {"prompt": "Valid prompt", "platform_preset": "unknown"},
        {
            "prompt": "Valid prompt",
            "platform_preset": "instagram_post",
            "provider": "gemini",
        },
        {
            "prompt": "Valid prompt",
            "platform_preset": "instagram_post",
            "model": "arbitrary",
        },
        {
            "prompt": "Valid prompt",
            "platform_preset": "instagram_post",
            "logo_mode": "both",
        },
    ],
)
def test_invalid_input_never_reaches_store(client, payload):
    api, store, _ = client
    response = api.post(
        f"/api/v1/brands/{BRAND}/generate",
        headers={"Idempotency-Key": str(uuid4())},
        json=payload,
    )
    assert response.status_code == 400
    assert not store.calls


def test_idempotency_header_is_required_and_must_be_uuid(client):
    api, store, _ = client
    for headers in ({}, {"Idempotency-Key": "invalid"}):
        response = api.post(
            f"/api/v1/brands/{BRAND}/generate",
            headers=headers,
            json={"prompt": "Valid prompt", "platform_preset": "instagram_post"},
        )
        assert response.status_code == 400
    assert not store.calls


@pytest.mark.parametrize("code", ["IDEMPOTENCY_CONFLICT", "OPENAI_KEY_REQUIRED"])
def test_conflicts_are_actionable(client, code):
    api, store, _ = client
    store.exception = GenerationConflict(code)
    response = api.post(
        f"/api/v1/brands/{BRAND}/generate",
        headers={"Idempotency-Key": str(uuid4())},
        json={"prompt": "Valid prompt", "platform_preset": "instagram_post"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == code


def test_cross_owner_get_and_list_never_sign_images(client):
    api, store, storage = client
    store.exception = LookupError("private data")
    for path in (
        f"/api/v1/brands/{BRAND}/generations",
        f"/api/v1/brands/{BRAND}/generations/{GENERATION}",
    ):
        response = api.get(path)
        assert response.status_code == 404
        assert "private data" not in response.text
    assert not storage.signs


def test_successful_image_get_gets_fresh_signed_url_and_expiry(client):
    api, store, storage = client
    store.value = {
        **row(),
        "status": "succeeded",
        "image_path": "private.png",
        "completed_at": datetime.now(UTC),
    }
    response = api.get(f"/api/v1/brands/{BRAND}/generations/{GENERATION}")
    assert response.status_code == 200
    assert storage.signs == ["private.png"]
    expires = datetime.fromisoformat(
        response.json()["image_url_expires_at"].replace("Z", "+00:00")
    )
    assert 290 < (expires - datetime.now(UTC)).total_seconds() <= 300


def test_cleanup_record_is_not_signed(client):
    api, store, storage = client
    store.value = {
        **row(),
        "status": "succeeded",
        "image_path": "private.png",
        "cleanup_required": True,
    }
    response = api.get(f"/api/v1/brands/{BRAND}/generations/{GENERATION}")
    assert response.json()["image_url"] is None
    assert not storage.signs


def test_list_pagination_and_filters(client):
    api, store, _ = client
    response = api.get(
        f"/api/v1/brands/{BRAND}/generations?page=2&per_page=10&status=failed&provider=openai"
    )
    assert response.status_code == 200
    assert response.json()["page"] == 2
    assert store.calls[-1] == (OWNER, BRAND, 2, 10, "openai", "failed")
    for query in ("page=0", "per_page=101", "provider=unknown", "status=unknown"):
        assert api.get(f"/api/v1/brands/{BRAND}/generations?{query}").status_code == 400


def test_unauthenticated_requests_are_rejected(client):
    api, _, _ = client
    app.dependency_overrides.pop(get_current_user)
    assert api.get(f"/api/v1/brands/{BRAND}/generations").status_code == 401
