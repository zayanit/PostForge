from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..config import get_engine
from ..models.profile import Profile, ProfileUpdate


@dataclass(frozen=True, slots=True)
class ProfileStore:
    engine: Engine

    def get_profile(self, user_id: str, email: str) -> Profile:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT user_id, full_name, avatar_url, created_at, updated_at
                    FROM profiles
                    WHERE user_id = :user_id
                    """
                ),
                {"user_id": user_id},
            ).mappings().one_or_none()

        if row is None:
            raise LookupError("Profile not found.")

        return Profile.model_validate({"email": email, **row})

    def update_profile(self, user_id: str, email: str, payload: ProfileUpdate) -> Profile:
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return self.get_profile(user_id, email)

        assignments: list[str] = []
        params: dict[str, Any] = {"user_id": user_id}

        for field, value in changes.items():
            assignments.append(f"{field} = :{field}")
            params[field] = value

        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    UPDATE profiles
                    SET {', '.join(assignments)}
                    WHERE user_id = :user_id
                    """
                ),
                params,
            )

        return self.get_profile(user_id, email)


@lru_cache(maxsize=1)
def get_profile_store() -> ProfileStore:
    return ProfileStore(get_engine())
