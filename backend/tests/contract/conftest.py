import os

import pytest


os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")


@pytest.fixture(autouse=True)
def bypass_database_privilege_check_for_contract_tests(monkeypatch: pytest.MonkeyPatch):
    from backend.app import main

    monkeypatch.setattr(main, "assert_database_role_privileges", lambda: None)
