from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

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


class BrandAssetOperationStaleError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class BrandAssetOperation:
    id: UUID
    brand_id: UUID
    operation: str
    object_path: str | None
    previous_path: str | None
    state: str
    remote_status: str


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
            {
                "id": row["id"],
                "name": row["name"],
                "logo_url": logo_url,
                "cleanup_state": cleanup_state,
                "kit_status": row.get("kit_status", "not_started"),
                "created_at": row["created_at"],
            }
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
                SELECT b.id, b.name, b.logo_path, b.deletion_state, b.created_at,
                       COALESCE(k.status::TEXT, 'not_started') AS kit_status
                FROM brands AS b
                LEFT JOIN brand_kits AS k ON k.brand_id = b.id
                WHERE b.id = :brand_id AND b.owner_user_id = :owner_user_id
                FOR UPDATE OF b
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
                    SELECT b.id, b.name, b.logo_path, b.deletion_state, b.created_at,
                           COALESCE(k.status::TEXT, 'not_started') AS kit_status
                    FROM brands AS b
                    LEFT JOIN brand_kits AS k ON k.brand_id = b.id
                    WHERE b.owner_user_id = :owner_user_id
                    ORDER BY b.created_at DESC, b.id DESC
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
                    SELECT b.id, b.name, b.logo_path, b.deletion_state, b.created_at,
                           COALESCE(k.status::TEXT, 'not_started') AS kit_status
                    FROM brands AS b
                    LEFT JOIN brand_kits AS k ON k.brand_id = b.id
                    WHERE b.id = :brand_id AND b.owner_user_id = :owner_user_id
                    """
                ),
                {"brand_id": brand_id, "owner_user_id": user_id},
            ).mappings().one_or_none()

        if row is None:
            raise LookupError("Brand not found.")

        return self._to_brand(row)

    def get_logo_path(self, user_id: str, brand_id: UUID) -> str | None:
        with self.engine.begin() as connection:
            row = self.lock_owned_brand_for_mutation(connection, user_id, brand_id)
        return row["logo_path"]

    def get_asset_operation(
        self, user_id: str, brand_id: UUID
    ) -> BrandAssetOperation | None:
        with self.engine.begin() as connection:
            self.lock_owned_brand(connection, user_id, brand_id)
            connection.execute(
                text(
                    """
                    UPDATE brand_asset_operations
                    SET state = 'cleanup_required', remote_status = 'unknown'
                    WHERE brand_id = :brand_id AND remote_status = 'pending'
                      AND started_at < clock_timestamp() - interval '5 minutes'
                    """
                ),
                {"brand_id": brand_id},
            )
            row = connection.execute(
                text(
                    """
                    SELECT id, brand_id, operation, object_path, previous_path,
                           state, remote_status
                    FROM brand_asset_operations
                    WHERE brand_id = :brand_id
                    FOR UPDATE
                    """
                ),
                {"brand_id": brand_id},
            ).mappings().one_or_none()
        return BrandAssetOperation(**row) if row is not None else None

    def begin_logo_upload(
        self, user_id: str, brand_id: UUID, extension: str
    ) -> BrandAssetOperation:
        operation_id = uuid4()
        object_path = f"brands/{brand_id}/logos/{operation_id}.{extension}"
        with self.engine.begin() as connection:
            brand = self.lock_owned_brand_without_asset_operation(
                connection, user_id, brand_id
            )
            row = connection.execute(
                text(
                    """
                    INSERT INTO brand_asset_operations (
                        id, brand_id, operation, object_path, previous_path,
                        state, remote_status
                    ) VALUES (
                        :id, :brand_id, 'upload', :object_path, :previous_path,
                        'in_progress', 'pending'
                    )
                    RETURNING id, brand_id, operation, object_path, previous_path,
                              state, remote_status
                    """
                ),
                {
                    "id": operation_id,
                    "brand_id": brand_id,
                    "object_path": object_path,
                    "previous_path": brand["logo_path"],
                },
            ).mappings().one()
        return BrandAssetOperation(**row)

    def begin_logo_remove(
        self, user_id: str, brand_id: UUID
    ) -> BrandAssetOperation | None:
        operation_id = uuid4()
        with self.engine.begin() as connection:
            brand = self.lock_owned_brand_without_asset_operation(
                connection, user_id, brand_id
            )
            if brand["logo_path"] is None:
                return None
            row = connection.execute(
                text(
                    """
                    INSERT INTO brand_asset_operations (
                        id, brand_id, operation, object_path, previous_path,
                        state, remote_status
                    ) VALUES (
                        :id, :brand_id, 'remove', :object_path, NULL,
                        'in_progress', 'pending'
                    )
                    RETURNING id, brand_id, operation, object_path, previous_path,
                              state, remote_status
                    """
                ),
                {
                    "id": operation_id,
                    "brand_id": brand_id,
                    "object_path": brand["logo_path"],
                },
            ).mappings().one()
        return BrandAssetOperation(**row)

    @staticmethod
    def _lock_operation(
        connection: Connection, brand_id: UUID, operation_id: UUID
    ) -> Mapping[str, Any]:
        operation = connection.execute(
            text(
                """
                SELECT id, brand_id, operation, object_path, previous_path,
                       state, remote_status
                FROM brand_asset_operations
                WHERE brand_id = :brand_id AND id = :operation_id
                FOR UPDATE
                """
            ),
            {"brand_id": brand_id, "operation_id": operation_id},
        ).mappings().one_or_none()
        if operation is None:
            raise BrandAssetOperationStaleError
        return operation

    def record_asset_remote_status(
        self,
        user_id: str,
        brand_id: UUID,
        operation_id: UUID,
        remote_status: str,
    ) -> None:
        if remote_status not in {"succeeded", "failed", "unknown"}:
            raise ValueError("Invalid remote status.")
        with self.engine.begin() as connection:
            self.lock_owned_brand(connection, user_id, brand_id)
            self._lock_operation(connection, brand_id, operation_id)
            connection.execute(
                text(
                    """
                    UPDATE brand_asset_operations
                    SET remote_status = :remote_status,
                        state = CASE WHEN :remote_status = 'succeeded'
                                     THEN state ELSE 'cleanup_required' END
                    WHERE id = :operation_id
                    """
                ),
                {"operation_id": operation_id, "remote_status": remote_status},
            )

    def abandon_definitive_asset_failure(
        self, user_id: str, brand_id: UUID, operation_id: UUID
    ) -> None:
        with self.engine.begin() as connection:
            self.lock_owned_brand(connection, user_id, brand_id)
            operation = self._lock_operation(connection, brand_id, operation_id)
            if operation["remote_status"] != "failed":
                raise BrandAssetOperationStaleError
            connection.execute(
                text("DELETE FROM brand_asset_operations WHERE id = :operation_id"),
                {"operation_id": operation_id},
            )

    def mark_asset_cleanup_required(
        self, user_id: str, brand_id: UUID, operation_id: UUID
    ) -> None:
        with self.engine.begin() as connection:
            self.lock_owned_brand(connection, user_id, brand_id)
            operation = self._lock_operation(connection, brand_id, operation_id)
            if operation["remote_status"] != "succeeded":
                raise BrandAssetOperationStaleError
            connection.execute(
                text(
                    "UPDATE brand_asset_operations SET state = 'cleanup_required' "
                    "WHERE id = :operation_id"
                ),
                {"operation_id": operation_id},
            )

    def publish_uploaded_logo(
        self, user_id: str, brand_id: UUID, operation_id: UUID
    ) -> Brand:
        with self.engine.begin() as connection:
            brand = self.lock_owned_brand_for_mutation(connection, user_id, brand_id)
            operation = self._lock_operation(connection, brand_id, operation_id)
            if (
                operation["operation"] != "upload"
                or operation["remote_status"] != "succeeded"
            ):
                raise BrandAssetOperationStaleError
            row = connection.execute(
                text(
                    """
                    UPDATE brands SET logo_path = :logo_path
                    WHERE id = :brand_id AND deletion_state = 'active'
                    RETURNING id, name, logo_path, deletion_state, created_at
                    """
                ),
                {"brand_id": brand_id, "logo_path": operation["object_path"]},
            ).mappings().one_or_none()
            if row is None:
                raise BrandAssetOperationStaleError
            row = {**row, "kit_status": brand["kit_status"]}
        return self._to_brand(row)

    def complete_asset_operation(
        self, user_id: str, brand_id: UUID, operation_id: UUID
    ) -> None:
        with self.engine.begin() as connection:
            brand = self.lock_owned_brand_for_mutation(connection, user_id, brand_id)
            operation = self._lock_operation(connection, brand_id, operation_id)
            if operation["remote_status"] != "succeeded":
                raise BrandAssetOperationStaleError
            if operation["operation"] == "upload":
                if brand["logo_path"] != operation["object_path"]:
                    raise BrandAssetOperationStaleError
            elif brand["logo_path"] != operation["object_path"]:
                raise BrandAssetOperationStaleError
            else:
                connection.execute(
                    text("UPDATE brands SET logo_path = NULL WHERE id = :brand_id"),
                    {"brand_id": brand_id},
                )
            connection.execute(
                text("DELETE FROM brand_asset_operations WHERE id = :operation_id"),
                {"operation_id": operation_id},
            )

    def mark_abandoned_asset_operations_unknown(self, brand_id: UUID) -> int:
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE brand_asset_operations
                    SET state = 'cleanup_required', remote_status = 'unknown'
                    WHERE brand_id = :brand_id AND remote_status = 'pending'
                      AND started_at < clock_timestamp() - interval '5 minutes'
                    """
                ),
                {"brand_id": brand_id},
            )
        return result.rowcount

    def fence_brand_for_deletion(
        self, user_id: str, brand_id: UUID, confirm_name: str
    ) -> None:
        with self.engine.begin() as connection:
            brand = self.lock_owned_brand(connection, user_id, brand_id)
            if brand["name"] != confirm_name:
                raise ValueError("Confirmation mismatch.")
            self.require_no_asset_operation(connection, brand_id)
            connection.execute(
                text(
                    """
                    UPDATE brands SET deletion_state = 'cleanup_required'
                    WHERE id = :brand_id AND deletion_state = 'active'
                    """
                ),
                {"brand_id": brand_id},
            )
            connection.execute(
                text(
                    """
                    UPDATE provider_keys
                    SET lifecycle = 'cleanup_required', is_active = false,
                        is_valid = NULL, last_validated_at = NULL,
                        last_validation_error = NULL, validation_token = NULL,
                        validation_lease_expires_at = NULL
                    WHERE brand_id = :brand_id
                    """
                ),
                {"brand_id": brand_id},
            )


@lru_cache(maxsize=1)
def get_brand_store() -> BrandStore:
    return BrandStore(get_engine())
