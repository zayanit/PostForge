from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ..config import load_settings
from ..models.login_attempt import LoginAttempt


LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15


def _coerce_datetime(value: datetime | str | None) -> datetime | None:
    # Raw text() queries return whatever type the driver hands back for a
    # timestamp column. Postgres/psycopg gives a native datetime, but
    # SQLite (used by this module's own test suite) can hand back an ISO
    # string instead, which breaks direct comparisons in is_locked().
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True)
class LoginAttemptState:
    email: str
    failed_count: int
    locked_until: datetime | None
    last_attempt_at: datetime


class LoginGuard:
    def __init__(self, engine: Engine):
        self._engine = engine

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    def get_state(self, email: str) -> LoginAttemptState | None:
        normalized_email = self.normalize_email(email)
        statement = text(
            """
            SELECT email, failed_count, locked_until, last_attempt_at
            FROM login_attempts
            WHERE email = :email
            """
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement, {"email": normalized_email}).mappings().one_or_none()

        if row is None:
            return None

        return LoginAttemptState(
            email=row["email"],
            failed_count=row["failed_count"],
            locked_until=_coerce_datetime(row["locked_until"]),
            last_attempt_at=_coerce_datetime(row["last_attempt_at"]),
        )

    def is_locked(self, email: str, now: datetime | None = None) -> bool:
        state = self.get_state(email)
        if state is None or state.locked_until is None:
            return False

        current_time = now or datetime.now(timezone.utc)
        return state.locked_until > current_time

    def record_failed_attempt(self, email: str, now: datetime | None = None) -> LoginAttemptState:
        normalized_email = self.normalize_email(email)
        current_time = now or datetime.now(timezone.utc)
        locked_until = current_time + timedelta(minutes=LOCKOUT_MINUTES)
        table = LoginAttempt.__tablename__

        # Single-statement upsert avoids lost updates under concurrent failures.
        statement = text(
            f"""
            INSERT INTO {table} (email, failed_count, locked_until, last_attempt_at)
            VALUES (:email, 1, NULL, :now)
            ON CONFLICT (email) DO UPDATE SET
              failed_count = CASE
                WHEN {table}.locked_until IS NOT NULL AND {table}.locked_until > :now THEN {table}.failed_count
                WHEN {table}.locked_until IS NOT NULL AND {table}.locked_until <= :now THEN 1
                ELSE {table}.failed_count + 1
              END,
              locked_until = CASE
                WHEN {table}.locked_until IS NOT NULL AND {table}.locked_until > :now THEN {table}.locked_until
                WHEN {table}.locked_until IS NOT NULL AND {table}.locked_until <= :now THEN NULL
                WHEN {table}.failed_count + 1 >= :threshold THEN :locked_until
                ELSE NULL
              END,
              last_attempt_at = CASE
                WHEN {table}.locked_until IS NOT NULL AND {table}.locked_until > :now THEN {table}.last_attempt_at
                ELSE :now
              END
            """
        )
        with self._engine.begin() as connection:
            connection.execute(
                statement,
                {
                    "email": normalized_email,
                    "now": current_time,
                    "threshold": LOCKOUT_THRESHOLD,
                    "locked_until": locked_until,
                },
            )

            row = connection.execute(
                text(
                    f"""
                    SELECT email, failed_count, locked_until, last_attempt_at
                    FROM {table}
                    WHERE email = :email
                    """
                ),
                {"email": normalized_email},
            ).mappings().one()

        return LoginAttemptState(
            email=row["email"],
            failed_count=row["failed_count"],
            locked_until=_coerce_datetime(row["locked_until"]),
            last_attempt_at=_coerce_datetime(row["last_attempt_at"]),
        )

    def reset(self, email: str) -> None:
        normalized_email = self.normalize_email(email)
        with self._engine.begin() as connection:
            connection.execute(text("DELETE FROM login_attempts WHERE email = :email"), {"email": normalized_email})


@lru_cache(maxsize=1)
def get_login_guard() -> LoginGuard:
    settings = load_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")

    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    return LoginGuard(engine)
