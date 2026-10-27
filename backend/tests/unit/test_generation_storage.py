import asyncio
from uuid import uuid4

import httpx
import pytest
from backend.app.services.brand_storage import BrandStorageError
from backend.app.services.generation_storage import GenerationStorage


def test_signed_url_has_five_minute_expiry_and_private_path():
    def handler(request):
        assert (
            request.url.path
            == "/storage/v1/object/sign/generation-assets/brands/test.png"
        )
        assert request.content == b'{"expiresIn":300}'
        return httpx.Response(
            200,
            json={
                "signedURL": (
                    "/object/sign/generation-assets/brands/test.png?" "token=temporary"
                )
            },
        )

    storage = GenerationStorage(
        "https://example.test", "secret", httpx.MockTransport(handler)
    )
    assert asyncio.run(storage.sign("brands/test.png")) == (
        "https://example.test/storage/v1/object/sign/generation-assets/bra"
        "nds/test.png?token=temporary"
    )
    assert "secret" not in repr(storage)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/image",
        "//evil.test/image",
        "/object/public/generation-assets/image",
    ],
)
def test_sign_rejects_wrong_hosts_or_public_urls(url):
    storage = GenerationStorage(
        "https://example.test",
        "secret",
        httpx.MockTransport(lambda _: httpx.Response(200, json={"signedURL": url})),
    )
    with pytest.raises(BrandStorageError):
        asyncio.run(storage.sign("image"))


@pytest.mark.parametrize(
    "status,body,exists",
    [(200, {}, True), (404, {}, False), (400, {"statusCode": "404"}, False)],
)
def test_object_presence(status, body, exists):
    storage = GenerationStorage(
        "https://example.test",
        "secret",
        httpx.MockTransport(lambda _: httpx.Response(status, json=body)),
    )
    assert asyncio.run(storage.object_exists("image")) is exists


def test_delete_retains_error_when_remote_object_still_exists():
    storage = GenerationStorage(
        "https://example.test",
        "secret",
        httpx.MockTransport(lambda _: httpx.Response(200, json={})),
    )
    with pytest.raises(BrandStorageError):
        asyncio.run(storage.delete("image"))


def test_private_bucket_prefix_cleanup_and_verification():
    brand = uuid4()
    path = f"brands/{brand}/generations/test.png"
    deleted = []

    def handler(request):
        if request.method == "DELETE":
            deleted.append(request.content)
            return httpx.Response(200, json=[])
        assert request.url.path == "/storage/v1/object/list/generation-assets"
        if deleted:
            return httpx.Response(200, json=[])
        import json

        prefix = json.loads(request.content)["prefix"]
        if prefix.endswith("generations"):
            return httpx.Response(
                200, json=[{"name": "test.png", "metadata": {"size": 20}}]
            )
        return httpx.Response(200, json=[{"name": "generations", "metadata": None}])

    storage = GenerationStorage(
        "https://example.test", "secret", httpx.MockTransport(handler)
    )
    asyncio.run(storage.delete_brand_prefix(brand))
    assert path.encode() in deleted[0]
    assert asyncio.run(storage.brand_prefix_is_empty(brand))
