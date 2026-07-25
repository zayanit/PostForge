from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote

import httpx

from ..config import load_settings


class BrandStorageError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class BrandStorage:
    supabase_url: str
    secret_key: str

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.secret_key,
            "Authorization": f"Bearer {self.secret_key}",
        }

    async def upload_logo(self, path: str, data: bytes, content_type: str) -> None:
        encoded_path = quote(path, safe="/")
        url = f"{self.supabase_url.rstrip('/')}/storage/v1/object/brand-assets/{encoded_path}"
        headers = {
            **self._headers,
            "Content-Type": content_type,
            "Cache-Control": "no-cache",
            "x-upsert": "true",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, content=data)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise BrandStorageError from exc

        if not response.is_success:
            raise BrandStorageError

    async def delete_logo(self, path: str) -> None:
        url = f"{self.supabase_url.rstrip('/')}/storage/v1/object/brand-assets"
        headers = {**self._headers, "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    "DELETE",
                    url,
                    headers=headers,
                    json={"prefixes": [path]},
                )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise BrandStorageError from exc

        if not response.is_success:
            raise BrandStorageError


@lru_cache(maxsize=1)
def get_brand_storage() -> BrandStorage:
    settings = load_settings()
    return BrandStorage(settings.supabase_url, settings.supabase_secret_key)
