from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from ..config import get_engine
from ..models.provider_key import ProviderKey, ProviderKeyAdd
from .brand_store import BrandCleanupRequiredError, BrandStore


class ProviderKeyStoreError(Exception):
    pass


class IdempotencyKeyRetiredError(ProviderKeyStoreError):
    pass


class VaultUnavailableError(ProviderKeyStoreError):
    pass


_SAFE_COLUMNS = """
    id, provider, label, key_hint, is_active, is_valid,
    last_validated_at, last_validation_error, lifecycle, created_at
"""


@dataclass(frozen=True, slots=True)
class ProviderKeyStore:
    engine: Engine

    @staticmethod
    def _to_provider_key(row: Mapping[str, Any]) -> ProviderKey:
        return ProviderKey.model_validate(
            {**row, "cleanup_state": row["lifecycle"]}
        )

    def list_keys(self, user_id: str, brand_id: UUID) -> list[ProviderKey]:
        with self.engine.begin() as connection:
            BrandStore.lock_owned_brand(connection, user_id, brand_id)
            rows = connection.execute(
                text(
                    f"""
                    SELECT {_SAFE_COLUMNS}
                    FROM provider_keys
                    WHERE brand_id = :brand_id
                    ORDER BY provider, created_at DESC, id DESC
                    """
                ),
                {"brand_id": brand_id},
            ).mappings().all()
        return [self._to_provider_key(row) for row in rows]

    def add_key(
        self,
        user_id: str,
        brand_id: UUID,
        payload: ProviderKeyAdd,
        idempotency_key: UUID,
    ) -> ProviderKey:
        try:
            with self.engine.begin() as connection:
                brand = BrandStore.lock_owned_brand(connection, user_id, brand_id)
                receipt = connection.execute(
                    text(
                        """
                        SELECT r.state, pk.id, pk.provider, pk.label, pk.key_hint,
                               pk.is_active, pk.is_valid, pk.last_validated_at,
                               pk.last_validation_error, pk.lifecycle, pk.created_at
                        FROM provider_key_idempotency r
                        LEFT JOIN provider_keys pk ON pk.id = r.provider_key_id
                        WHERE r.brand_id = :brand_id AND r.request_id = :request_id
                        """
                    ),
                    {"brand_id": brand_id, "request_id": idempotency_key},
                ).mappings().one_or_none()
                if receipt is not None:
                    if receipt["state"] != "active" or receipt["id"] is None:
                        raise IdempotencyKeyRetiredError
                    return self._to_provider_key(receipt)

                BrandStore.require_normal_brand(brand)
                cleanup_pending = connection.execute(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM provider_keys "
                        "WHERE brand_id = :brand_id AND lifecycle = 'cleanup_required'"
                        ")"
                    ),
                    {"brand_id": brand_id},
                ).scalar_one()
                if cleanup_pending:
                    raise BrandCleanupRequiredError

                key_id = uuid4()
                if payload.make_active:
                    connection.execute(
                        text(
                            "UPDATE provider_keys SET is_active = false "
                            "WHERE brand_id = :brand_id "
                            "AND provider = CAST(:provider AS provider_t) "
                            "AND is_active"
                        ),
                        {"brand_id": brand_id, "provider": payload.provider.value},
                    )

                vault_secret_id = connection.execute(
                    text(
                        "SELECT vault.create_secret(:secret, NULL, '', NULL)"
                    ),
                    {"secret": payload.key},
                ).scalar_one()
                row = connection.execute(
                    text(
                        f"""
                        INSERT INTO provider_keys
                            (id, brand_id, provider, vault_secret_id, label,
                             key_hint, is_active)
                        VALUES
                            (:id, :brand_id, CAST(:provider AS provider_t),
                             :vault_secret_id, :label,
                             :key_hint, :is_active)
                        RETURNING {_SAFE_COLUMNS}
                        """
                    ),
                    {
                        "id": key_id,
                        "brand_id": brand_id,
                        "provider": payload.provider.value,
                        "vault_secret_id": vault_secret_id,
                        "label": payload.label,
                        "key_hint": f"***{payload.key[-4:]}",
                        "is_active": payload.make_active,
                    },
                ).mappings().one()
                connection.execute(
                    text(
                        "INSERT INTO provider_key_idempotency "
                        "(id, brand_id, request_id, provider_key_id, state) "
                        "VALUES (:id, :brand_id, :request_id, :provider_key_id, 'active')"
                    ),
                    {
                        "id": uuid4(),
                        "brand_id": brand_id,
                        "request_id": idempotency_key,
                        "provider_key_id": key_id,
                    },
                )
            return self._to_provider_key(row)
        except (
            LookupError,
            BrandCleanupRequiredError,
            IdempotencyKeyRetiredError,
        ):
            raise
        except SQLAlchemyError as exc:
            raise VaultUnavailableError from exc


@lru_cache(maxsize=1)
def get_provider_key_store() -> ProviderKeyStore:
    return ProviderKeyStore(get_engine())
