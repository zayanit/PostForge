from datetime import datetime

from sqlalchemy import DateTime, Integer, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    email: Mapped[str] = mapped_column(String, primary_key=True)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
