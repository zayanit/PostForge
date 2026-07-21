from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend.app.models.profile import ProfileUpdate
from backend.app.services.profile_store import ProfileStore


def test_profile_store_updates_profiles_row_against_real_sqlite():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE profiles (
                  user_id TEXT PRIMARY KEY,
                  full_name TEXT,
                  avatar_url TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO profiles (user_id, full_name, avatar_url, created_at, updated_at)
                VALUES (:user_id, NULL, NULL, :created_at, :updated_at)
                """
            ),
            {
                "user_id": "11111111-1111-1111-1111-111111111111",
                "created_at": datetime(2026, 7, 19, tzinfo=timezone.utc).isoformat(),
                "updated_at": datetime(2026, 7, 19, tzinfo=timezone.utc).isoformat(),
            },
        )

    store = ProfileStore(engine)
    updated = store.update_profile(
        "11111111-1111-1111-1111-111111111111",
        "jane@example.com",
        ProfileUpdate(full_name="Jane Doe", avatar_url="https://example.com/avatar.png"),
    )

    assert updated.full_name == "Jane Doe"
    assert updated.avatar_url == "https://example.com/avatar.png"

    with engine.connect() as connection:
        row = connection.execute(text("SELECT full_name, avatar_url FROM profiles WHERE user_id = :user_id"), {"user_id": "11111111-1111-1111-1111-111111111111"}).mappings().one()

    assert row["full_name"] == "Jane Doe"
    assert row["avatar_url"] == "https://example.com/avatar.png"
