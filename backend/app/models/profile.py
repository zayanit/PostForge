from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfileBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str | None = Field(default=None)
    avatar_url: str | None = Field(default=None)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None

        if not 2 <= len(value) <= 120:
            raise ValueError("full_name must be between 2 and 120 characters.")

        return value

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, value: str | None) -> str | None:
        if value is None:
            return None

        if not re.fullmatch(r"https?://.+", value):
            raise ValueError("avatar_url must be a valid URL.")

        return value


class Profile(ProfileBase):
    user_id: UUID
    email: str
    created_at: datetime
    updated_at: datetime


class ProfileUpdate(ProfileBase):
    pass
