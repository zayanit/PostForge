from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from backend.tests.integration.test_provider_keys import (
    MockProviderValidator,
    ProviderFixture,
    SecretFixture,
    _add_real_key,
    _provider_validator_dependency,
    provider_fixture,
)


def _add_provider_key(
    client: TestClient,
    fixture: ProviderFixture,
    provider: str,
    suffix: str,
) -> UUID:
    response = client.post(
        f"/api/v1/brands/{fixture['brand_id']}/keys",
        headers={**fixture["headers"], "Idempotency-Key": str(uuid4())},
        json={
            "provider": provider,
            "key": f"activation-{uuid4().hex}-{suffix}",
            "make_active": False,
        },
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])


def _active_states(fixture: ProviderFixture) -> dict[UUID, bool]:
    with fixture["engine"].connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, is_active FROM provider_keys "
                "WHERE brand_id = :brand_id"
            ),
            {"brand_id": fixture["brand_id"]},
        ).all()
    return {row.id: row.is_active for row in rows}


def test_simultaneous_same_provider_activation_keeps_exactly_one_active(
    provider_fixture,
):
    from backend.app.main import app

    fixture = provider_fixture
    with TestClient(app) as setup_client:
        first_id = _add_provider_key(setup_client, fixture, "openai", "A1B2")
        second_id = _add_provider_key(setup_client, fixture, "openai", "C3_D")

    with TestClient(app) as first_client, TestClient(app) as second_client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = [
                executor.submit(
                    client.patch,
                    f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/activate",
                    headers=fixture["headers"],
                )
                for client, key_id in (
                    (first_client, first_id),
                    (second_client, second_id),
                )
            ]
            completed = [future.result(timeout=10) for future in responses]

    assert [response.status_code for response in completed] == [200, 200]
    states = _active_states(fixture)
    assert sum(states[key_id] for key_id in (first_id, second_id)) == 1
    observable = "".join(response.text for response in completed)
    for unsafe in ("uq_provider_keys_one_active", "provider_keys_invalid_inactive", "UPDATE provider_keys"):
        assert unsafe not in observable


def test_activation_is_independent_per_provider(provider_fixture):
    from backend.app.main import app

    fixture = provider_fixture
    with TestClient(app) as client:
        openai_id = _add_provider_key(client, fixture, "openai", "E5-F")
        gemini_id = _add_provider_key(client, fixture, "gemini", "G7_H")
        openai = client.patch(
            f"/api/v1/brands/{fixture['brand_id']}/keys/{openai_id}/activate",
            headers=fixture["headers"],
        )
        gemini = client.patch(
            f"/api/v1/brands/{fixture['brand_id']}/keys/{gemini_id}/activate",
            headers=fixture["headers"],
        )

    assert openai.status_code == gemini.status_code == 200
    states = _active_states(fixture)
    assert states[openai_id] is True
    assert states[gemini_id] is True


def test_invalid_validation_completion_wins_after_activation(provider_fixture):
    from backend.app.main import app

    fixture = provider_fixture
    raw_key = SecretFixture(f"activation-validation-{uuid4().hex}-J8_K")
    validator = MockProviderValidator(
        ("invalid", "INVALID_CREDENTIAL"),
        expected_secret=raw_key,
        block_first=True,
    )
    dependency = _provider_validator_dependency()
    app.dependency_overrides[dependency] = lambda: validator
    try:
        with TestClient(app) as validation_client, TestClient(app) as activation_client:
            key_id = _add_real_key(
                validation_client, fixture, raw_key, make_active=False
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(
                    validation_client.post,
                    f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/validate",
                    headers=fixture["headers"],
                )
                assert validator.entered.wait(5)
                activated = activation_client.patch(
                    f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/activate",
                    headers=fixture["headers"],
                )
                validator.release.set()
                invalidated = pending.result(timeout=10)
    finally:
        app.dependency_overrides.pop(dependency, None)

    assert activated.status_code == 200
    assert invalidated.status_code == 200
    assert invalidated.json()["outcome"] == "invalid"
    with fixture["engine"].connect() as connection:
        state = connection.execute(
            text("SELECT is_valid, is_active FROM provider_keys WHERE id = :key_id"),
            {"key_id": key_id},
        ).one()
    assert state == (False, False)


def test_activation_is_blocked_after_invalid_validation(provider_fixture):
    from backend.app.main import app

    fixture = provider_fixture
    raw_key = SecretFixture(f"invalid-before-activation-{uuid4().hex}-L9_M")
    validator = MockProviderValidator(
        ("invalid", "INVALID_CREDENTIAL"), expected_secret=raw_key
    )
    dependency = _provider_validator_dependency()
    app.dependency_overrides[dependency] = lambda: validator
    try:
        with TestClient(app) as client:
            key_id = _add_real_key(client, fixture, raw_key, make_active=False)
            invalidated = client.post(
                f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/validate",
                headers=fixture["headers"],
            )
            activated = client.patch(
                f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/activate",
                headers=fixture["headers"],
            )
    finally:
        app.dependency_overrides.pop(dependency, None)

    assert invalidated.status_code == 200
    assert activated.status_code == 409
    assert activated.json()["error"]["code"] == "KEY_INVALID"
    assert activated.json()["error"]["message"] == (
        "Validate this key successfully before activating it."
    )
    assert activated.headers["X-Request-Id"] == activated.json()["error"]["request_id"]


def test_database_rejects_multiple_active_invalid_and_cleanup_active_rows(
    provider_fixture,
):
    from backend.app.main import app

    fixture = provider_fixture
    with TestClient(app) as client:
        first_id = _add_provider_key(client, fixture, "openai", "N0_P")
        second_id = _add_provider_key(client, fixture, "openai", "Q1_R")

    engine = fixture["engine"]
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE provider_keys SET is_active = true WHERE id = :key_id"),
            {"key_id": first_id},
        )
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE provider_keys SET is_active = true WHERE id = :key_id"),
                {"key_id": second_id},
            )
    for assignment in (
        "is_valid = false, last_validated_at = clock_timestamp(), "
        "last_validation_error = 'INVALID_CREDENTIAL', is_active = true",
        "lifecycle = 'cleanup_required', is_active = true",
    ):
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(f"UPDATE provider_keys SET {assignment} WHERE id = :key_id"),
                    {"key_id": second_id},
                )


def test_individual_delete_removes_active_secret_retires_receipt_and_has_no_replacement(
    provider_fixture,
):
    from backend.app.main import app

    fixture = provider_fixture
    with TestClient(app) as client:
        active_id = _add_real_key(
            client,
            fixture,
            SecretFixture(f"delete-active-{uuid4().hex}-A1B2"),
            make_active=True,
        )
        inactive_id = _add_real_key(
            client,
            fixture,
            SecretFixture(f"delete-inactive-{uuid4().hex}-C3D4"),
            make_active=False,
        )
        deleted = client.delete(
            f"/api/v1/brands/{fixture['brand_id']}/keys/{active_id}",
            headers=fixture["headers"],
        )

    assert deleted.status_code == 204
    with fixture["engine"].connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM provider_keys WHERE id = :id"),
            {"id": active_id},
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT is_active FROM provider_keys WHERE id = :id"),
            {"id": inactive_id},
        ).scalar_one() is False
        receipt = connection.execute(
            text(
                "SELECT state, provider_key_id FROM provider_key_idempotency "
                "WHERE brand_id = :brand_id AND state = 'deleted'"
            ),
            {"brand_id": fixture["brand_id"]},
        ).one()
    assert receipt == ("deleted", None)


def test_individual_delete_accepts_missing_secret_and_reconciles_cleanup_row(
    provider_fixture,
):
    from backend.app.main import app

    fixture = provider_fixture
    with TestClient(app) as client:
        key_id = _add_real_key(
            client,
            fixture,
            SecretFixture(f"delete-missing-{uuid4().hex}-E5F6"),
            make_active=True,
        )
        with fixture["engine"].begin() as connection:
            vault_id = connection.execute(
                text("SELECT vault_secret_id FROM provider_keys WHERE id = :id"),
                {"id": key_id},
            ).scalar_one()
            connection.execute(
                text("DELETE FROM vault.secrets WHERE id = :id"), {"id": vault_id}
            )
            connection.execute(
                text(
                    """
                    UPDATE provider_keys
                    SET lifecycle = 'cleanup_required', is_active = false,
                        is_valid = NULL, last_validated_at = NULL,
                        last_validation_error = NULL, validation_token = NULL,
                        validation_lease_expires_at = NULL
                    WHERE id = :id
                    """
                ),
                {"id": key_id},
            )
        deleted = client.delete(
            f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}",
            headers=fixture["headers"],
        )
        repeated = client.delete(
            f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}",
            headers=fixture["headers"],
        )

    assert deleted.status_code == 204
    assert repeated.status_code == 404


def test_individual_delete_gives_brand_cleanup_precedence_and_retains_key(
    provider_fixture,
):
    from backend.app.main import app

    fixture = provider_fixture
    with TestClient(app) as client:
        key_id = _add_real_key(
            client,
            fixture,
            SecretFixture(f"delete-brand-fence-{uuid4().hex}-G7H8"),
            make_active=True,
        )
        with fixture["engine"].begin() as connection:
            connection.execute(
                text(
                    "UPDATE brands SET deletion_state = 'cleanup_required' "
                    "WHERE id = :brand_id"
                ),
                {"brand_id": fixture["brand_id"]},
            )
        response = client.delete(
            f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}",
            headers=fixture["headers"],
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BRAND_CLEANUP_REQUIRED"
    with fixture["engine"].connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM provider_keys WHERE id = :id"),
            {"id": key_id},
        ).scalar_one() == 1


def test_individual_vault_failure_keeps_fence_and_retry_finishes_cleanup(
    provider_fixture,
):
    from backend.app.main import app
    from backend.app.routes.provider_keys import get_provider_key_store
    from backend.app.services.provider_key_store import ProviderKeyStore

    class FailingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, parameters=None):
            if "DELETE FROM vault.secrets" in str(statement):
                raise SQLAlchemyError("injected vault failure")
            return self.connection.execute(statement, parameters)

    class FailingCleanupEngine:
        def __init__(self, engine):
            self.engine = engine
            self.transactions = 0

        @contextmanager
        def begin(self):
            self.transactions += 1
            with self.engine.begin() as connection:
                if self.transactions == 2:
                    yield FailingConnection(connection)
                else:
                    yield connection

    fixture = provider_fixture
    with TestClient(app) as client:
        key_id = _add_real_key(
            client,
            fixture,
            SecretFixture(f"delete-vault-retry-{uuid4().hex}-N3P4"),
            make_active=True,
        )
        failing_store = ProviderKeyStore(FailingCleanupEngine(fixture["engine"]))
        app.dependency_overrides[get_provider_key_store] = lambda: failing_store
        try:
            failed = client.delete(
                f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}",
                headers=fixture["headers"],
            )
        finally:
            app.dependency_overrides.pop(get_provider_key_store, None)

        assert failed.status_code == 503
        assert failed.json()["error"]["code"] == "KEY_CLEANUP_REQUIRED"
        with fixture["engine"].connect() as connection:
            retained = connection.execute(
                text(
                    """
                    SELECT lifecycle, is_active, validation_token,
                           validation_lease_expires_at,
                           EXISTS (
                             SELECT 1 FROM vault.secrets
                             WHERE id = provider_keys.vault_secret_id
                           ) AS secret_exists
                    FROM provider_keys WHERE id = :id
                    """
                ),
                {"id": key_id},
            ).one()
        assert retained == ("cleanup_required", False, None, None, True)

        activation = client.patch(
            f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/activate",
            headers=fixture["headers"],
        )
        validation = client.post(
            f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}/validate",
            headers=fixture["headers"],
        )
        retried = client.delete(
            f"/api/v1/brands/{fixture['brand_id']}/keys/{key_id}",
            headers=fixture["headers"],
        )

    assert activation.status_code == validation.status_code == 409
    assert activation.json()["error"]["code"] == "KEY_CLEANUP_REQUIRED"
    assert validation.json()["error"]["code"] == "KEY_CLEANUP_REQUIRED"
    assert retried.status_code == 204


def test_asset_operation_is_unique_unknown_non_expiring_and_stale_completion_is_blocked(
    provider_fixture,
):
    from backend.app.services.brand_store import (
        BrandAssetOperationStaleError,
        BrandMutationInProgressError,
        BrandStore,
    )

    fixture = provider_fixture
    store = BrandStore(fixture["engine"])
    with fixture["engine"].connect() as connection:
        user_id = connection.execute(
            text("SELECT owner_user_id FROM brands WHERE id = :id"),
            {"id": fixture["brand_id"]},
        ).scalar_one()
    operation = store.begin_logo_upload(user_id, fixture["brand_id"], "png")
    try:
        with pytest.raises(BrandMutationInProgressError):
            store.begin_logo_remove(user_id, fixture["brand_id"])
        with fixture["engine"].begin() as connection:
            connection.execute(
                text(
                    "UPDATE brand_asset_operations "
                    "SET started_at = clock_timestamp() - interval '1 hour' "
                    "WHERE id = :id"
                ),
                {"id": operation.id},
            )
        assert store.mark_abandoned_asset_operations_unknown(fixture["brand_id"]) == 1
        assert store.mark_abandoned_asset_operations_unknown(fixture["brand_id"]) == 0
        with fixture["engine"].connect() as connection:
            state = connection.execute(
                text(
                    "SELECT state, remote_status FROM brand_asset_operations "
                    "WHERE id = :id"
                ),
                {"id": operation.id},
            ).one()
        assert state == ("cleanup_required", "unknown")
        with pytest.raises(BrandAssetOperationStaleError):
            store.complete_asset_operation(user_id, fixture["brand_id"], uuid4())
    finally:
        with fixture["engine"].begin() as connection:
            connection.execute(
                text("DELETE FROM brand_asset_operations WHERE id = :id"),
                {"id": operation.id},
            )


def test_brand_hard_delete_removes_legacy_tokenized_storage_vault_and_all_rows(
    provider_fixture,
    monkeypatch: pytest.MonkeyPatch,
):
    from backend.app.main import app
    from backend.app.services.brand_storage import BrandStorage, get_brand_storage

    fixture = provider_fixture
    storage = get_brand_storage()
    monkeypatch.setattr(BrandStorage, "PAGE_SIZE", 1)
    monkeypatch.setattr(BrandStorage, "DELETE_BATCH_SIZE", 1)
    seeded_paths = (
        f"brands/{fixture['brand_id']}/logo.png",
        f"brands/{fixture['brand_id']}/archive/legacy.webp",
        f"brands/{fixture['brand_id']}/logos/orphan.jpg",
    )
    for path in seeded_paths:
        asyncio.run(storage.upload_logo(path, b"legacy", "image/png"))
    with TestClient(app) as client:
        _add_real_key(
            client,
            fixture,
            SecretFixture(f"brand-delete-a-{uuid4().hex}-J9K0"),
            make_active=True,
        )
        _add_real_key(
            client,
            fixture,
            SecretFixture(f"brand-delete-b-{uuid4().hex}-L1M2"),
            make_active=False,
        )
        logo = client.post(
            f"/api/v1/brands/{fixture['brand_id']}/logo",
            headers=fixture["headers"],
            files={"file": ("logo.png", b"\x89PNG\r\n\x1a\nlogo", "image/png")},
        )
        assert logo.status_code == 200
        with fixture["engine"].connect() as connection:
            secret_ids = connection.execute(
                text(
                    "SELECT vault_secret_id FROM provider_keys "
                    "WHERE brand_id = :brand_id"
                ),
                {"brand_id": fixture["brand_id"]},
            ).scalars().all()
        deleted = client.request(
            "DELETE",
            f"/api/v1/brands/{fixture['brand_id']}",
            headers=fixture["headers"],
            json={"confirm_name": "Provider Keys Integration"},
        )

    assert deleted.status_code == 204
    with fixture["engine"].connect() as connection:
        assert connection.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM brands WHERE id = :brand_id) +
                  (SELECT count(*) FROM provider_keys WHERE brand_id = :brand_id) +
                  (SELECT count(*) FROM provider_key_idempotency WHERE brand_id = :brand_id) +
                  (SELECT count(*) FROM brand_asset_operations WHERE brand_id = :brand_id)
                """
            ),
            {"brand_id": fixture["brand_id"]},
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT count(*) FROM vault.secrets WHERE id = ANY(:ids)"),
            {"ids": secret_ids},
        ).scalar_one() == 0
    assert asyncio.run(storage.brand_prefix_is_empty(fixture["brand_id"]))


def test_brand_vault_failure_rolls_back_and_retry_completes(provider_fixture):
    from backend.app.main import app
    from backend.app.routes.brands import get_brand_deletion
    from backend.app.services.brand_deletion import BrandDeletion
    from backend.app.services.brand_storage import get_brand_storage
    from backend.app.services.brand_store import BrandStore

    class FailingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, parameters=None):
            if "DELETE FROM vault.secrets" in str(statement):
                raise SQLAlchemyError("injected brand vault failure")
            return self.connection.execute(statement, parameters)

    class FailingEngine:
        def __init__(self, engine):
            self.engine = engine

        @contextmanager
        def begin(self):
            with self.engine.begin() as connection:
                yield FailingConnection(connection)

    fixture = provider_fixture
    with TestClient(app) as client:
        key_id = _add_real_key(
            client,
            fixture,
            SecretFixture(f"brand-vault-retry-{uuid4().hex}-R5S6"),
            make_active=True,
        )
        failing_deletion = BrandDeletion(
            FailingEngine(fixture["engine"]),
            BrandStore(fixture["engine"]),
            get_brand_storage(),
        )
        app.dependency_overrides[get_brand_deletion] = lambda: failing_deletion
        try:
            failed = client.request(
                "DELETE",
                f"/api/v1/brands/{fixture['brand_id']}",
                headers=fixture["headers"],
                json={"confirm_name": "Provider Keys Integration"},
            )
        finally:
            app.dependency_overrides.pop(get_brand_deletion, None)

        assert failed.status_code == 503
        assert failed.json()["error"]["code"] == "BRAND_CLEANUP_REQUIRED"
        with fixture["engine"].connect() as connection:
            retained = connection.execute(
                text(
                    "SELECT b.deletion_state, pk.lifecycle, pk.is_active, "
                    "EXISTS (SELECT 1 FROM vault.secrets "
                    "WHERE id = pk.vault_secret_id) AS secret_exists "
                    "FROM brands b JOIN provider_keys pk ON pk.brand_id = b.id "
                    "WHERE b.id = :brand_id AND pk.id = :key_id"
                ),
                {"brand_id": fixture["brand_id"], "key_id": key_id},
            ).one()
        assert retained == ("cleanup_required", "cleanup_required", False, True)

        retried = client.request(
            "DELETE",
            f"/api/v1/brands/{fixture['brand_id']}",
            headers=fixture["headers"],
            json={"confirm_name": "Provider Keys Integration"},
        )

    assert retried.status_code == 204
    with fixture["engine"].connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM brands WHERE id = :brand_id"),
            {"brand_id": fixture["brand_id"]},
        ).scalar_one() == 0
