from __future__ import annotations

import asyncio
import json
from uuid import UUID

import httpx
import pytest

from backend.app.services.brand_storage import (
    BrandStorage,
    BrandStorageUnknownError,
)


def test_upload_uses_token_owned_path_without_upsert():
    observed: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["path"] = request.url.path
        observed["upsert"] = request.headers["x-upsert"]
        return httpx.Response(200)

    storage = BrandStorage(
        "https://example.supabase.co", "secret", httpx.MockTransport(handler)
    )
    brand_id = UUID("11111111-1111-1111-1111-111111111111")
    operation_id = UUID("22222222-2222-2222-2222-222222222222")
    path = storage.logo_path(brand_id, operation_id, "png")

    asyncio.run(storage.upload_logo(path, b"png", "image/png"))

    assert path == f"brands/{brand_id}/logos/{operation_id}.png"
    assert observed == {
        "path": f"/storage/v1/object/brand-assets/{path}",
        "upsert": "false",
    }


def test_upload_transport_failure_is_an_unknown_remote_outcome():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("ambiguous", request=request)

    storage = BrandStorage(
        "https://example.supabase.co", "secret", httpx.MockTransport(handler)
    )

    with pytest.raises(BrandStorageUnknownError):
        asyncio.run(
            storage.upload_logo(
                "brands/brand/logos/token.png", b"png", "image/png"
            )
        )


def test_prefix_cleanup_restarts_at_zero_and_removes_nested_and_legacy_objects():
    brand_id = UUID("11111111-1111-1111-1111-111111111111")
    prefix = f"brands/{brand_id}"
    objects = {
        f"{prefix}/logo.png",
        f"{prefix}/logos/token.png",
        f"{prefix}/nested/archive/legacy.webp",
    }
    list_offsets: list[tuple[str, int]] = []
    deleted_batches: list[list[str]] = []

    def children(directory: str) -> list[dict[str, object]]:
        direct_objects: set[str] = set()
        direct_folders: set[str] = set()
        marker = f"{directory}/"
        for path in objects:
            if not path.startswith(marker):
                continue
            remainder = path[len(marker) :]
            first, separator, _ = remainder.partition("/")
            if separator:
                direct_folders.add(first)
            else:
                direct_objects.add(first)
        return [
            {"name": name, "metadata": None} for name in sorted(direct_folders)
        ] + [
            {"name": name, "metadata": {"size": 1}}
            for name in sorted(direct_objects)
        ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/object/list/brand-assets"):
            payload = json.loads(request.content)
            directory = payload["prefix"]
            offset = payload["offset"]
            list_offsets.append((directory, offset))
            page = children(directory)[offset : offset + payload["limit"]]
            return httpx.Response(200, json=page)
        if request.method == "DELETE":
            paths = json.loads(request.content)["prefixes"]
            deleted_batches.append(paths)
            objects.difference_update(paths)
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    storage = BrandStorage(
        "https://example.supabase.co", "secret", httpx.MockTransport(handler)
    )
    asyncio.run(storage.delete_brand_prefix(brand_id))

    assert objects == set()
    assert {path for batch in deleted_batches for path in batch} == {
        f"{prefix}/logo.png",
        f"{prefix}/logos/token.png",
        f"{prefix}/nested/archive/legacy.webp",
    }
    assert list_offsets.count((prefix, 0)) >= 3
