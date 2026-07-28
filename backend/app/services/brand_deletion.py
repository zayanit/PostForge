from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from ..config import get_engine
from .brand_storage import BrandStorage, BrandStorageError, get_brand_storage
from .brand_store import BrandStore, get_brand_store


class BrandConfirmationMismatchError(Exception):
    pass


class BrandDeletionCleanupError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class BrandDeletion:
    engine: Engine
    brand_store: BrandStore
    storage: BrandStorage

    async def delete(self, user_id: str, brand_id: UUID, confirm_name: str) -> None:
        try:
            self.brand_store.fence_brand_for_deletion(
                user_id, brand_id, confirm_name
            )
        except ValueError as exc:
            raise BrandConfirmationMismatchError from exc

        try:
            await self.storage.delete_brand_prefix(brand_id)
            if not await self.storage.brand_prefix_is_empty(brand_id):
                raise BrandStorageError
        except BrandStorageError as exc:
            raise BrandDeletionCleanupError from exc

        try:
            self._delete_database_dependencies(user_id, brand_id)
        except (LookupError, BrandDeletionCleanupError):
            raise
        except SQLAlchemyError as exc:
            raise BrandDeletionCleanupError from exc

    def _delete_database_dependencies(self, user_id: str, brand_id: UUID) -> None:
        with self.engine.begin() as connection:
            brand = BrandStore.lock_owned_brand(connection, user_id, brand_id)
            BrandStore.require_no_asset_operation(connection, brand_id)
            if brand["deletion_state"] != "cleanup_required":
                raise BrandDeletionCleanupError
            secret_ids = connection.execute(
                text(
                    "SELECT vault_secret_id FROM provider_keys "
                    "WHERE brand_id = :brand_id FOR UPDATE"
                ),
                {"brand_id": brand_id},
            ).scalars().all()
            if secret_ids:
                connection.execute(
                    text("DELETE FROM vault.secrets WHERE id = ANY(:secret_ids)"),
                    {"secret_ids": list(secret_ids)},
                )
                remaining_secrets = connection.execute(
                    text(
                        "SELECT count(*) FROM vault.secrets "
                        "WHERE id = ANY(:secret_ids)"
                    ),
                    {"secret_ids": list(secret_ids)},
                ).scalar_one()
                if remaining_secrets:
                    raise BrandDeletionCleanupError
            connection.execute(
                text("DELETE FROM provider_key_idempotency WHERE brand_id = :brand_id"),
                {"brand_id": brand_id},
            )
            connection.execute(
                text("DELETE FROM provider_keys WHERE brand_id = :brand_id"),
                {"brand_id": brand_id},
            )
            remaining = connection.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM provider_keys WHERE brand_id = :brand_id) +
                      (SELECT count(*) FROM provider_key_idempotency WHERE brand_id = :brand_id) +
                      (SELECT count(*) FROM brand_asset_operations WHERE brand_id = :brand_id)
                    """
                ),
                {"brand_id": brand_id},
            ).scalar_one()
            if remaining:
                raise BrandDeletionCleanupError
            deleted = connection.execute(
                text(
                    "DELETE FROM brands WHERE id = :brand_id "
                    "AND owner_user_id = :user_id RETURNING id"
                ),
                {"brand_id": brand_id, "user_id": user_id},
            ).scalar_one_or_none()
            if deleted is None:
                raise LookupError("Brand not found.")
            if connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM brands WHERE id = :brand_id)"),
                {"brand_id": brand_id},
            ).scalar_one():
                raise BrandDeletionCleanupError


@lru_cache(maxsize=1)
def get_brand_deletion() -> BrandDeletion:
    return BrandDeletion(get_engine(), get_brand_store(), get_brand_storage())
