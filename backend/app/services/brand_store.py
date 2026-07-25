from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from ..config import get_engine, load_settings
from ..models.brand import Brand, BrandCreate


class BrandNameTakenError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class BrandStore:
    engine: Engine

    @staticmethod
    def _to_brand(row: Mapping[str, Any]) -> Brand:
        logo_path = row["logo_path"]
        logo_url = None
        if logo_path:
            base_url = load_settings().supabase_url.rstrip("/")
            logo_url = f"{base_url}/storage/v1/object/public/brand-assets/{logo_path}"
        return Brand.model_validate({"logo_url": logo_url, **row})

    def create_brand(self, user_id: str, payload: BrandCreate) -> Brand:
        try:
            with self.engine.begin() as connection:
                row = connection.execute(
                    text(
                        """
                        INSERT INTO brands (owner_user_id, name)
                        VALUES (:owner_user_id, :name)
                        RETURNING id, name, logo_path, created_at
                        """
                    ),
                    {"owner_user_id": user_id, "name": payload.name},
                ).mappings().one()
        except IntegrityError as exc:
            original = exc.orig
            constraint_name = getattr(getattr(original, "diag", None), "constraint_name", None)
            if getattr(original, "pgcode", None) == "23505" and constraint_name == "uq_brands_owner_name_ci":
                raise BrandNameTakenError from exc
            raise

        return self._to_brand(row)

    def list_brands(self, user_id: str) -> list[Brand]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT id, name, logo_path, created_at
                    FROM brands
                    WHERE owner_user_id = :owner_user_id
                    ORDER BY created_at DESC, id DESC
                    """
                ),
                {"owner_user_id": user_id},
            ).mappings().all()

        return [self._to_brand(row) for row in rows]

    def get_brand(self, user_id: str, brand_id: UUID) -> Brand:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id, name, logo_path, created_at
                    FROM brands
                    WHERE id = :brand_id AND owner_user_id = :owner_user_id
                    """
                ),
                {"brand_id": brand_id, "owner_user_id": user_id},
            ).mappings().one_or_none()

        if row is None:
            raise LookupError("Brand not found.")

        return self._to_brand(row)

    def get_logo_path(self, user_id: str, brand_id: UUID) -> str | None:
        with self.engine.connect() as connection:
            logo_path = connection.execute(
                text(
                    """
                    SELECT logo_path
                    FROM brands
                    WHERE id = :brand_id AND owner_user_id = :owner_user_id
                    """
                ),
                {"brand_id": brand_id, "owner_user_id": user_id},
            ).scalar_one_or_none()

        if logo_path is None:
            self.get_brand(user_id, brand_id)
        return logo_path

    def update_logo_path(
        self,
        user_id: str,
        brand_id: UUID,
        logo_path: str | None,
    ) -> Brand:
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    UPDATE brands
                    SET logo_path = :logo_path
                    WHERE id = :brand_id AND owner_user_id = :owner_user_id
                    RETURNING id, name, logo_path, created_at
                    """
                ),
                {
                    "brand_id": brand_id,
                    "owner_user_id": user_id,
                    "logo_path": logo_path,
                },
            ).mappings().one_or_none()

        if row is None:
            raise LookupError("Brand not found.")
        return self._to_brand(row)

    def delete_brand(self, user_id: str, brand_id: UUID) -> None:
        with self.engine.begin() as connection:
            deleted_id = connection.execute(
                text(
                    """
                    DELETE FROM brands
                    WHERE id = :brand_id AND owner_user_id = :owner_user_id
                    RETURNING id
                    """
                ),
                {"brand_id": brand_id, "owner_user_id": user_id},
            ).scalar_one_or_none()

        if deleted_id is None:
            raise LookupError("Brand not found.")


@lru_cache(maxsize=1)
def get_brand_store() -> BrandStore:
    return BrandStore(get_engine())
