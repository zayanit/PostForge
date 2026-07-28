from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol
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


class KeyCleanupRequiredError(ProviderKeyStoreError):
    pass


class ValidationResult(Protocol):
    outcome: str


@dataclass(frozen=True, slots=True)
class ValidationClaim:
    attempted_at: datetime
    key: ProviderKey = field(repr=False)
    provider: str
    secret: str | None = field(repr=False)
    token: UUID | None = field(repr=False)
    in_progress: bool


@dataclass(frozen=True, slots=True)
class ValidationCompletion:
    key: ProviderKey = field(repr=False)
    superseded: bool


_SAFE_COLUMNS = """
    id, provider, label, key_hint, is_active, is_valid,
    last_validated_at, last_validation_error, lifecycle, created_at
"""

_SAFE_PK_COLUMNS = """
    pk.id AS id, pk.provider AS provider, pk.label AS label,
    pk.key_hint AS key_hint, pk.is_active AS is_active,
    pk.is_valid AS is_valid, pk.last_validated_at AS last_validated_at,
    pk.last_validation_error AS last_validation_error,
    pk.lifecycle AS lifecycle, pk.created_at AS created_at
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

    def claim_validation(
        self,
        user_id: str,
        brand_id: UUID,
        key_id: UUID,
        deadline: float,
    ) -> ValidationClaim:
        cleanup_required = False
        claim: ValidationClaim | None = None
        try:
            with self.engine.begin() as connection:
                brand = BrandStore.lock_owned_brand(connection, user_id, brand_id)
                row = connection.execute(
                    text(
                        f"""
                        SELECT {_SAFE_PK_COLUMNS}, pk.validation_token,
                               pk.validation_lease_expires_at,
                               ds.decrypted_secret,
                               clock_timestamp() AS attempted_at
                        FROM provider_keys pk
                        LEFT JOIN vault.decrypted_secrets ds
                          ON ds.id = pk.vault_secret_id
                        WHERE pk.brand_id = :brand_id AND pk.id = :key_id
                        FOR UPDATE OF pk
                        """
                    ),
                    {"brand_id": brand_id, "key_id": key_id},
                ).mappings().one_or_none()
                if row is None:
                    raise LookupError("Provider key not found.")

                # Resolve ownership and path membership before exposing either fence.
                if brand["deletion_state"] != "active":
                    raise BrandCleanupRequiredError
                if row["lifecycle"] != "normal":
                    raise KeyCleanupRequiredError

                if row["decrypted_secret"] is None:
                    connection.execute(
                        text(
                            """
                            UPDATE provider_keys
                            SET lifecycle = 'cleanup_required', is_active = false,
                                is_valid = NULL, last_validated_at = NULL,
                                last_validation_error = NULL,
                                validation_token = NULL,
                                validation_lease_expires_at = NULL
                            WHERE id = :key_id
                            """
                        ),
                        {"key_id": key_id},
                    )
                    cleanup_required = True
                elif (
                    row["validation_token"] is not None
                    and row["validation_lease_expires_at"] > row["attempted_at"]
                ):
                    claim = ValidationClaim(
                        attempted_at=row["attempted_at"],
                        key=self._to_provider_key(row),
                        provider=row["provider"],
                        secret=None,
                        token=None,
                        in_progress=True,
                    )
                else:
                    lease_seconds = deadline - time.monotonic()
                    if lease_seconds <= 0:
                        raise VaultUnavailableError
                    token = uuid4()
                    connection.execute(
                        text(
                            """
                            UPDATE provider_keys
                            SET validation_token = :token,
                                validation_lease_expires_at =
                                    clock_timestamp()
                                    + make_interval(secs => :lease_seconds)
                            WHERE id = :key_id
                            """
                        ),
                        {
                            "key_id": key_id,
                            "token": token,
                            "lease_seconds": lease_seconds,
                        },
                    )
                    claim = ValidationClaim(
                        attempted_at=row["attempted_at"],
                        key=self._to_provider_key(row),
                        provider=row["provider"],
                        secret=row["decrypted_secret"],
                        token=token,
                        in_progress=False,
                    )
        except (LookupError, BrandCleanupRequiredError, KeyCleanupRequiredError):
            raise
        except SQLAlchemyError as exc:
            raise VaultUnavailableError from exc

        if cleanup_required:
            # Raising outside the transaction preserves the irreversible cleanup fence.
            raise KeyCleanupRequiredError
        assert claim is not None
        return claim

    def complete_validation(
        self,
        user_id: str,
        brand_id: UUID,
        key_id: UUID,
        token: UUID,
        result: ValidationResult,
        deadline: float,
    ) -> ValidationCompletion:
        del deadline  # Database pool, lock, and statement waits are bounded by the engine.
        try:
            with self.engine.begin() as connection:
                brand = BrandStore.lock_owned_brand(connection, user_id, brand_id)
                row = connection.execute(
                    text(
                        f"""
                        SELECT {_SAFE_COLUMNS}, validation_token,
                               validation_lease_expires_at,
                               clock_timestamp() AS database_now
                        FROM provider_keys
                        WHERE brand_id = :brand_id AND id = :key_id
                        FOR UPDATE
                        """
                    ),
                    {"brand_id": brand_id, "key_id": key_id},
                ).mappings().one_or_none()
                if row is None:
                    raise LookupError("Provider key not found.")

                token_matches = row["validation_token"] == token
                lease_is_live = (
                    row["validation_lease_expires_at"] is not None
                    and row["validation_lease_expires_at"] > row["database_now"]
                )
                if not token_matches or not lease_is_live:
                    if token_matches:
                        connection.execute(
                            text(
                                "UPDATE provider_keys "
                                "SET validation_token = NULL, "
                                "validation_lease_expires_at = NULL "
                                "WHERE id = :key_id AND validation_token = :token"
                            ),
                            {"key_id": key_id, "token": token},
                        )
                    return ValidationCompletion(
                        key=self._to_provider_key(row), superseded=True
                    )

                BrandStore.require_normal_brand(brand)
                if row["lifecycle"] != "normal":
                    raise KeyCleanupRequiredError

                if result.outcome == "valid":
                    assignments = """
                        is_valid = true,
                        last_validated_at = clock_timestamp(),
                        last_validation_error = NULL,
                    """
                elif result.outcome == "invalid":
                    assignments = """
                        is_active = false,
                        is_valid = false,
                        last_validated_at = clock_timestamp(),
                        last_validation_error = 'INVALID_CREDENTIAL',
                    """
                else:
                    assignments = ""

                completed = connection.execute(
                    text(
                        f"""
                        UPDATE provider_keys
                        SET {assignments}
                            validation_token = NULL,
                            validation_lease_expires_at = NULL
                        WHERE id = :key_id AND validation_token = :token
                        RETURNING {_SAFE_COLUMNS}
                        """
                    ),
                    {"key_id": key_id, "token": token},
                ).mappings().one()
                return ValidationCompletion(
                    key=self._to_provider_key(completed), superseded=False
                )
        except (
            LookupError,
            BrandCleanupRequiredError,
            KeyCleanupRequiredError,
        ):
            raise
        except SQLAlchemyError as exc:
            raise VaultUnavailableError from exc


@lru_cache(maxsize=1)
def get_provider_key_store() -> ProviderKeyStore:
    return ProviderKeyStore(get_engine())
