from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote
from uuid import UUID

import httpx

from ..config import load_settings


class BrandStorageError(Exception):
    """A Storage operation did not complete safely."""


class BrandStorageUnknownError(BrandStorageError):
    """The remote outcome may have been committed and must remain fenced."""


@dataclass(frozen=True, slots=True, repr=False)
class BrandStorage:
    supabase_url: str
    secret_key: str
    transport: httpx.AsyncBaseTransport | None = None

    PAGE_SIZE = 100
    DELETE_BATCH_SIZE = 100
    MAX_CLEANUP_BATCHES = 1_000

    def __repr__(self) -> str:
        return "<BrandStorage redacted>"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.secret_key,
            "Authorization": f"Bearer {self.secret_key}",
        }

    @staticmethod
    def logo_path(brand_id: UUID, operation_id: UUID, extension: str) -> str:
        return f"brands/{brand_id}/logos/{operation_id}.{extension}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=30.0, transport=self.transport)

    async def upload_logo(self, path: str, data: bytes, content_type: str) -> None:
        encoded_path = quote(path, safe="/")
        url = f"{self.supabase_url.rstrip('/')}/storage/v1/object/brand-assets/{encoded_path}"
        headers = {
            **self._headers,
            "Content-Type": content_type,
            "Cache-Control": "no-cache",
            "x-upsert": "false",
        }
        try:
            async with self._client() as client:
                response = await client.post(url, headers=headers, content=data)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise BrandStorageUnknownError from exc
        if not response.is_success:
            if response.status_code >= 500:
                raise BrandStorageUnknownError
            raise BrandStorageError

    async def object_exists(self, path: str) -> bool:
        encoded_path = quote(path, safe="/")
        url = f"{self.supabase_url.rstrip('/')}/storage/v1/object/brand-assets/{encoded_path}"
        try:
            async with self._client() as client:
                response = await client.head(url, headers=self._headers)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise BrandStorageUnknownError from exc
        if response.status_code in {400, 404}:
            return False
        if not response.is_success:
            if response.status_code >= 500:
                raise BrandStorageUnknownError
            raise BrandStorageError
        return True

    async def delete_logo(self, path: str) -> None:
        await self._delete_paths([path])
        if await self.object_exists(path):
            raise BrandStorageError

    async def _list_directory(
        self, prefix: str, offset: int = 0
    ) -> list[dict[str, object]]:
        url = f"{self.supabase_url.rstrip('/')}/storage/v1/object/list/brand-assets"
        payload = {
            "prefix": prefix.rstrip("/"),
            "limit": self.PAGE_SIZE,
            "offset": offset,
            "sortBy": {"column": "name", "order": "asc"},
        }
        try:
            async with self._client() as client:
                response = await client.post(
                    url,
                    headers={**self._headers, "Content-Type": "application/json"},
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise BrandStorageUnknownError from exc
        if not response.is_success:
            if response.status_code >= 500:
                raise BrandStorageUnknownError
            raise BrandStorageError
        value = response.json()
        if not isinstance(value, list):
            raise BrandStorageError
        return value

    async def _list_prefix_page(self, root: str) -> list[str]:
        objects: list[str] = []
        directories = [(root.rstrip("/"), 0)]
        visited: set[tuple[str, int]] = set()
        while directories and len(objects) < self.PAGE_SIZE:
            directory, offset = directories.pop()
            page_key = (directory, offset)
            if page_key in visited:
                continue
            visited.add(page_key)
            items = await self._list_directory(directory, offset)
            if len(items) == self.PAGE_SIZE:
                directories.append((directory, offset + self.PAGE_SIZE))
            for item in items:
                name = item.get("name")
                if not isinstance(name, str) or not name or "/" in name:
                    raise BrandStorageError
                path = f"{directory}/{name}"
                if item.get("metadata") is None:
                    directories.append((path, 0))
                else:
                    objects.append(path)
                    if len(objects) == self.PAGE_SIZE:
                        break
        return objects

    async def _delete_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        url = f"{self.supabase_url.rstrip('/')}/storage/v1/object/brand-assets"
        try:
            async with self._client() as client:
                response = await client.request(
                    "DELETE",
                    url,
                    headers={**self._headers, "Content-Type": "application/json"},
                    json={"prefixes": paths},
                )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise BrandStorageUnknownError from exc
        if not response.is_success:
            if response.status_code >= 500:
                raise BrandStorageUnknownError
            raise BrandStorageError

    async def delete_brand_prefix(self, brand_id: UUID) -> None:
        prefix = f"brands/{brand_id}"
        for _ in range(self.MAX_CLEANUP_BATCHES):
            paths = await self._list_prefix_page(prefix)
            if not paths:
                # A separate final read prevents a transient empty page from authorizing
                # physical deletion.
                if await self._list_prefix_page(prefix):
                    continue
                return
            for start in range(0, len(paths), self.DELETE_BATCH_SIZE):
                await self._delete_paths(paths[start : start + self.DELETE_BATCH_SIZE])
        raise BrandStorageError

    async def brand_prefix_is_empty(self, brand_id: UUID) -> bool:
        return not await self._list_prefix_page(f"brands/{brand_id}")


@lru_cache(maxsize=1)
def get_brand_storage() -> BrandStorage:
    settings = load_settings()
    return BrandStorage(settings.supabase_url, settings.supabase_secret_key)
