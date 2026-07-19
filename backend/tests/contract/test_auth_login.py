from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routes import auth as auth_module
from backend.app.routes.auth import get_login_guard
from backend.app.services.login_guard import LoginAttemptState


class FakeLoginGuard:
    def __init__(self, locked: bool = False):
        self.locked = locked
        self.failed_count = 0
        self.reset_calls = 0
        self.recorded_emails: list[str] = []

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    def is_locked(self, email: str, now=None) -> bool:
        return self.locked

    def record_failed_attempt(self, email: str, now=None):
        self.failed_count += 1
        self.recorded_emails.append(email)
        return LoginAttemptState(email=email, failed_count=self.failed_count, locked_until=None, last_attempt_at=now)

    def reset(self, email: str) -> None:
        self.reset_calls += 1


def test_login_success_returns_supabase_token_payload():
    guard = FakeLoginGuard()
    app.dependency_overrides[get_login_guard] = lambda: guard

    async def fake_exchange(email: str, password: str):
        return {
            "access_token": "eyJ...",
            "refresh_token": "...",
            "token_type": "bearer",
            "expires_in": 3600,
        }

    original = auth_module.exchange_password_for_token
    auth_module.exchange_password_for_token = fake_exchange

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "jane@example.com", "password": "correct horse battery staple"},
            )

        assert response.status_code == 200
        assert response.json()["token_type"] == "bearer"
        assert guard.reset_calls == 1
    finally:
        auth_module.exchange_password_for_token = original
        app.dependency_overrides.clear()


def test_login_invalid_credentials_returns_generic_400():
    guard = FakeLoginGuard()
    app.dependency_overrides[get_login_guard] = lambda: guard

    async def fake_exchange(email: str, password: str):
        raise auth_module.InvalidCredentialsError()

    original = auth_module.exchange_password_for_token
    auth_module.exchange_password_for_token = fake_exchange

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "jane@example.com", "password": "wrong"},
            )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
        assert guard.failed_count == 1
    finally:
        auth_module.exchange_password_for_token = original
        app.dependency_overrides.clear()


def test_login_locked_out_returns_429_without_calling_provider():
    guard = FakeLoginGuard(locked=True)
    app.dependency_overrides[get_login_guard] = lambda: guard

    async def fake_exchange(email: str, password: str):
        raise AssertionError("provider should not be called when locked")

    original = auth_module.exchange_password_for_token
    auth_module.exchange_password_for_token = fake_exchange

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "jane@example.com", "password": "correct horse battery staple"},
            )

        assert response.status_code == 429
        assert response.json()["error"]["code"] == "ACCOUNT_TEMPORARILY_LOCKED"
        assert guard.failed_count == 0
    finally:
        auth_module.exchange_password_for_token = original
        app.dependency_overrides.clear()


def test_login_provider_unavailable_returns_502_without_incrementing_failures():
    guard = FakeLoginGuard()
    app.dependency_overrides[get_login_guard] = lambda: guard

    async def fake_exchange(email: str, password: str):
        raise auth_module.ProviderUnavailableError()

    original = auth_module.exchange_password_for_token
    auth_module.exchange_password_for_token = fake_exchange

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "jane@example.com", "password": "wrong"},
            )

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"
        assert guard.failed_count == 0
    finally:
        auth_module.exchange_password_for_token = original
        app.dependency_overrides.clear()
