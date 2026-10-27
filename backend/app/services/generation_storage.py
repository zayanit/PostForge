from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote
from uuid import UUID

import httpx

from ..config import load_settings
from .brand_storage import BrandStorage, BrandStorageError, BrandStorageUnknownError


@dataclass(frozen=True, slots=True, repr=False)
class GenerationStorage(BrandStorage):
    @staticmethod
    def path(brand_id: UUID, generation_id: UUID) -> str:
        return f"brands/{brand_id}/generations/{generation_id}.png"

    def _url(self, path: str = "", operation: str = "") -> str:
        suffix = f"/{quote(path, safe='/')}" if path else ""
        base = self.supabase_url.rstrip("/")
        return f"{base}/storage/v1/object/{operation}generation-assets{suffix}"

    async def upload(self, path: str, data: bytes) -> None:
        try:
            async with self._client() as client:
                response = await client.post(
                    self._url(path),
                    content=data,
                    headers={
                        **self._headers,
                        "Content-Type": "image/png",
                        "x-upsert": "false",
                        "Cache-Control": "no-store",
                    },
                )
        except httpx.RequestError as exc:
            raise BrandStorageUnknownError from exc
        if not response.is_success:
            raise BrandStorageUnknownError

    async def object_exists(self, path: str) -> bool:
        try:
            async with self._client() as client:
                response = await client.get(
                    self._url(path, "info/"), headers=self._headers
                )
        except httpx.RequestError as exc:
            raise BrandStorageUnknownError from exc
        if response.status_code == 404:
            return False
        if response.status_code == 400:
            # Supabase Storage can wrap object-not-found in an HTTP 400.
            try:
                if str(response.json().get("statusCode")) == "404":
                    return False
            except ValueError:
                pass
            raise BrandStorageUnknownError
        if not response.is_success:
            raise BrandStorageUnknownError
        return True

    async def sign(self, path: str) -> str:
        try:
            async with self._client() as client:
                response = await client.post(
                    self._url(path, "sign/"),
                    headers=self._headers,
                    json={"expiresIn": 300},
                )
            response.raise_for_status()
            signed = response.json()["signedURL"]
            # Do not accept an arbitrary host from a remote response.
            if not isinstance(signed, str) or not signed.startswith(
                "/object/sign/generation-assets/"
            ):
                raise ValueError
            return f"{self.supabase_url.rstrip('/')}/storage/v1{signed}"
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            raise BrandStorageError from exc

    async def _delete_paths(self, paths: list[str]) -> None:
        try:
            async with self._client() as client:
                response = await client.request(
                    "DELETE",
                    self._url(),
                    headers=self._headers,
                    json={"prefixes": paths},
                )
        except httpx.RequestError as exc:
            raise BrandStorageUnknownError from exc
        if not response.is_success:
            raise BrandStorageUnknownError

    async def delete(self, path: str) -> None:
        await self._delete_paths([path])
        if await self.object_exists(path):
            raise BrandStorageError

    async def _list_directory(self, prefix: str, offset: int = 0):
        try:
            async with self._client() as client:
                response = await client.post(
                    self._url(operation="list/"),
                    headers=self._headers,
                    json={
                        "prefix": prefix.rstrip("/"),
                        "limit": self.PAGE_SIZE,
                        "offset": offset,
                        "sortBy": {"column": "name", "order": "asc"},
                    },
                )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, list):
                raise ValueError
            return result
        except (httpx.HTTPError, ValueError) as exc:
            raise BrandStorageUnknownError from exc


@lru_cache(maxsize=1)
def get_generation_storage() -> GenerationStorage:
    settings = load_settings()
    return GenerationStorage(settings.supabase_url, settings.supabase_secret_key)
