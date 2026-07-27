from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from ..config import get_engine, load_settings
from ..models.brand import Brand, BrandCreate


class BrandNameTakenError(Exception):
    pass


class BrandCleanupRequiredError(Exception):
    pass


class BrandMutationInProgressError(Exception):
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
        cleanup_state = {
            "active": "normal",
            "cleanup_required": "cleanup_required",
        }[row["deletion_state"]]
        return Brand.model_validate(
            {"logo_url": logo_url, "cleanup_state": cleanup_state, **row}
        )

    @staticmethod
    def lock_owned_brand(
        connection: Connection,
        user_id: str,
        brand_id: UUID,
    ) -> Mapping[str, Any]:
        row = connection.execute(
            text(
                """
                SELECT id, name, logo_path, deletion_state, created_at
                FROM brands
                WHERE id = :brand_id AND owner_user_id = :owner_user_id
                FOR UPDATE
                """
            ),
            {"brand_id": brand_id, "owner_user_id": user_id},
        ).mappings().one_or_none()
        if row is None:
            raise LookupError("Brand not found.")
        return row

    @staticmethod
    def require_normal_brand(row: Mapping[str, Any]) -> None:
        if row["deletion_state"] != "active":
            raise BrandCleanupRequiredError

    @staticmethod
    def require_no_asset_operation(connection: Connection, brand_id: UUID) -> None:
        operation_exists = connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM brand_asset_operations WHERE brand_id = :brand_id
                )
                """
            ),
            {"brand_id": brand_id},
        ).scalar_one()
        if operation_exists:
            raise BrandMutationInProgressError

    def lock_owned_brand_for_mutation(
        self,
        connection: Connection,
        user_id: str,
        brand_id: UUID,
    ) -> Mapping[str, Any]:
        row = self.lock_owned_brand(connection, user_id, brand_id)
        self.require_normal_brand(row)
        return row

    def lock_owned_brand_without_asset_operation(
        self,
        connection: Connection,
        user_id: str,
        brand_id: UUID,
    ) -> Mapping[str, Any]:
        row = self.lock_owned_brand_for_mutation(connection, user_id, brand_id)
        self.require_no_asset_operation(connection, brand_id)
        return row

    def get_brand_for_mutation(self, user_id: str, brand_id: UUID) -> Brand:
        with self.engine.begin() as connection:
            row = self.lock_owned_brand_without_asset_operation(
                connection, user_id, brand_id
            )
        return self._to_brand(row)

    def create_brand(self, user_id: str, payload: BrandCreate) -> Brand:
        try:
            with self.engine.begin() as connection:
                row = connection.execute(
                    text(
                        """
                        INSERT INTO brands (owner_user_id, name)
                        VALUES (:owner_user_id, :name)
                        RETURNING id, name, logo_path, deletion_state, created_at
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
                    SELECT id, name, logo_path, deletion_state, created_at
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
                    SELECT id, name, logo_path, deletion_state, created_at
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
        with self.engine.begin() as connection:
            row = self.lock_owned_brand_without_asset_operation(
                connection, user_id, brand_id
            )
        return row["logo_path"]

    def begin_brand_cleanup(self, user_id: str, brand_id: UUID) -> str | None:
        with self.engine.begin() as connection:
            row = self.lock_owned_brand(connection, user_id, brand_id)
            self.require_no_asset_operation(connection, brand_id)
            if row["deletion_state"] == "active":
                row = connection.execute(
                    text(
                        """
                        UPDATE brands
                        SET deletion_state = 'cleanup_required'
                        WHERE id = :brand_id AND owner_user_id = :owner_user_id
                        RETURNING id, name, logo_path, deletion_state, created_at
                        """
                    ),
                    {"brand_id": brand_id, "owner_user_id": user_id},
                ).mappings().one_or_none()

            if row is None:
                raise LookupError("Brand not found.")
            return row["logo_path"]

    def update_logo_path(
        self,
        user_id: str,
        brand_id: UUID,
        logo_path: str | None,
    ) -> Brand:
        with self.engine.begin() as connection:
            self.lock_owned_brand_without_asset_operation(
                connection, user_id, brand_id
            )
            row = connection.execute(
                text(
                    """
                    UPDATE brands
                    SET logo_path = :logo_path
                    WHERE id = :brand_id AND owner_user_id = :owner_user_id
                    RETURNING id, name, logo_path, deletion_state, created_at
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

    def mark_cleanup_required(self, user_id: str, brand_id: UUID) -> Brand:
        with self.engine.begin() as connection:
            current = self.lock_owned_brand(connection, user_id, brand_id)
            self.require_no_asset_operation(connection, brand_id)
            if current["deletion_state"] == "cleanup_required":
                return self._to_brand(current)
            row = connection.execute(
                text(
                    """
                    UPDATE brands
                    SET deletion_state = 'cleanup_required'
                    WHERE id = :brand_id AND owner_user_id = :owner_user_id
                    RETURNING id, name, logo_path, deletion_state, created_at
                    """
                ),
                {"brand_id": brand_id, "owner_user_id": user_id},
            ).mappings().one_or_none()

        if row is None:
            raise LookupError("Brand not found.")
        return self._to_brand(row)

    def delete_brand_after_cleanup(self, user_id: str, brand_id: UUID) -> None:
        with self.engine.begin() as connection:
            current = self.lock_owned_brand(connection, user_id, brand_id)
            self.require_no_asset_operation(connection, brand_id)
            if current["deletion_state"] != "cleanup_required":
                raise BrandCleanupRequiredError
            has_provider_keys = connection.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM provider_keys WHERE brand_id = :brand_id"
                    ")"
                ),
                {"brand_id": brand_id},
            ).scalar_one()
            if has_provider_keys:
                raise BrandCleanupRequiredError
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
