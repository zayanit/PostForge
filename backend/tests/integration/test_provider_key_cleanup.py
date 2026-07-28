from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

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
