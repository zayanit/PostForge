from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


_COLOR_PATTERN = re.compile(r"#[0-9A-Fa-f]{6}\Z")


class KitStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"


class Tone(str, Enum):
    FORMAL = "formal"
    CASUAL = "casual"
    PLAYFUL = "playful"
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"


class BrandKitAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tagline: str | None = None
    tone: Tone | None = None
    audience: str | None = None
    colors: list[str] = Field(default_factory=list)
    avoid_words: str | None = None

    @field_validator("tagline", "audience", "avoid_words", mode="before")
    @classmethod
    def trim_nullable_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None

    @field_validator("tone", mode="before")
    @classmethod
    def clear_blank_tone(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("tagline")
    @classmethod
    def validate_tagline(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 160:
            raise ValueError("tagline must be 160 characters or fewer.")
        return value

    @field_validator("audience")
    @classmethod
    def validate_audience(cls, value: str | None) -> str | None:
        if value is not None and not 2 <= len(value) <= 500:
            raise ValueError("audience must be between 2 and 500 characters.")
        return value

    @field_validator("colors", mode="before")
    @classmethod
    def clear_null_colors(cls, value: object) -> object:
        return [] if value is None else value

    @field_validator("colors")
    @classmethod
    def normalize_colors(cls, value: list[str]) -> list[str]:
        if len(value) > 3:
            raise ValueError("colors must contain no more than 3 values.")

        normalized = [color.strip().upper() for color in value]
        if any(_COLOR_PATTERN.fullmatch(color) is None for color in normalized):
            raise ValueError("colors must use the #RRGGBB format.")
        return normalized


class BrandKitUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    answers: BrandKitAnswers = Field(default_factory=BrandKitAnswers)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not 2 <= len(normalized) <= 120:
            raise ValueError("name must be between 2 and 120 characters.")
        return normalized


class BrandKit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_id: UUID
    brand_name: str
    answers: BrandKitAnswers
    summary: str | None
    status: KitStatus
    completed_at: datetime | None
    updated_at: datetime | None
