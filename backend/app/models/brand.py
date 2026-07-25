from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


class BrandCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip(" ")
        if not 2 <= len(normalized) <= 120:
            raise ValueError("name must be between 2 and 120 characters.")
        return normalized


class Brand(BaseModel):
    id: UUID
    name: str
    logo_url: str | None
    created_at: datetime
