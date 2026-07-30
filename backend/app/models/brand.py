from __future__ import annotations

from datetime import datetime
from typing import Literal
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


class BrandDelete(BaseModel):
    confirm_name: str | None = None


class Brand(BaseModel):
    id: UUID
    name: str
    logo_url: str | None
    cleanup_state: Literal["normal", "cleanup_required"] = "normal"
    kit_status: Literal["not_started", "in_progress", "complete"] = "not_started"
    created_at: datetime


class BrandListResponse(BaseModel):
    brands: list[Brand]
