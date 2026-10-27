from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..presets import PRESETS

GenerationStatus = Literal["pending", "processing", "succeeded", "failed"]


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=3, max_length=4000, repr=False)
    platform_preset: str
    provider: Literal["openai"] = "openai"
    model: Literal["gpt-image-2"] = "gpt-image-2"

    @field_validator("prompt")
    @classmethod
    def trim_prompt(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Enter a prompt of 3–4,000 characters.")
        return value

    @field_validator("platform_preset")
    @classmethod
    def known_preset(cls, value: str) -> str:
        if value not in PRESETS:
            raise ValueError("Choose a supported platform preset.")
        return value


class Generation(BaseModel):
    id: UUID
    brand_id: UUID
    prompt: str = Field(repr=False)
    provider: Literal["openai"] = "openai"
    model: Literal["gpt-image-2"] = "gpt-image-2"
    platform_preset: str
    width: int
    height: int
    status: GenerationStatus
    error_code: str | None = None
    image_url: str | None = Field(default=None, repr=False)
    image_url_expires_at: datetime | None = None
    cleanup_required: bool = False
    created_at: datetime
    completed_at: datetime | None = None


class GenerationList(BaseModel):
    generations: list[Generation]
    page: int
    per_page: int
    total: int
