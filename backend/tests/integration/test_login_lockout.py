from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from backend.app.main import app
from backend.app.models.login_attempt import LoginAttempt
from backend.app.routes import auth as auth_module
from backend.app.routes.auth import get_login_guard
from backend.app.services.login_guard import LoginGuard


def make_guard() -> LoginGuard:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    LoginAttempt.metadata.create_all(engine)
    return LoginGuard(engine)


def test_login_lockout_flow_is_identical_for_registered_and_unregistered_emails():
    guard = make_guard()

    for attempt in range(1, 5):
        state = guard.record_failed_attempt("registered@example.com", now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert state.failed_count == attempt
        assert state.locked_until is None

    fifth = guard.record_failed_attempt("registered@example.com", now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert fifth.failed_count == 5
    assert fifth.locked_until is not None
    assert guard.is_locked("registered@example.com", now=datetime(2026, 1, 1, tzinfo=timezone.utc))

    guard.reset("registered@example.com")
    assert guard.get_state("registered@example.com") is None

    for _ in range(5):
        guard.record_failed_attempt("never-registered@example.com", now=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert guard.is_locked("never-registered@example.com", now=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_concurrent_failed_attempts_are_not_lost(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'lockout.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    LoginAttempt.metadata.create_all(engine)
    guard = LoginGuard(engine)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    guard.record_failed_attempt("race@example.com", now=now)

    def attempt() -> None:
        guard.record_failed_attempt("race@example.com", now=now)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: attempt(), range(2)))

    state = guard.get_state("race@example.com")
    assert state is not None
    assert state.failed_count == 3


def test_provider_timeout_or_5xx_does_not_increment_failed_count():
    guard = make_guard()

    app.dependency_overrides[get_login_guard] = lambda: guard

    async def fake_exchange(email: str, password: str):
        raise auth_module.ProviderUnavailableError()

    original = auth_module.exchange_password_for_token
    auth_module.exchange_password_for_token = fake_exchange

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "provider-failure@example.com", "password": "wrong-password"},
            )

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"
        assert guard.get_state("provider-failure@example.com") is None
    finally:
        auth_module.exchange_password_for_token = original
        app.dependency_overrides.clear()
