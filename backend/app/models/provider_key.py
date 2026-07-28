from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


_KEY_SUFFIX = re.compile(r"[A-Za-z0-9_-]{4}$")


class Provider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"


class ProviderKeyLifecycle(str, Enum):
    NORMAL = "normal"
    CLEANUP_REQUIRED = "cleanup_required"


class ProviderValidationOutcome(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    TEMPORARY = "temporary"


class ProviderValidationCode(str, Enum):
    VALID = "VALID"
    INVALID_CREDENTIAL = "INVALID_CREDENTIAL"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_PERMISSION = "PROVIDER_PERMISSION"
    VALIDATION_UNDETERMINED = "VALIDATION_UNDETERMINED"
    VALIDATION_IN_PROGRESS = "VALIDATION_IN_PROGRESS"
    VALIDATION_SUPERSEDED = "VALIDATION_SUPERSEDED"


class ProviderKeyAdd(BaseModel):
    provider: Provider
    key: str = Field(repr=False)
    label: str | None = Field(default=None, repr=False)
    make_active: bool = True

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if len(value) < 5 or not value.strip() or _KEY_SUFFIX.search(value) is None:
            raise ValueError(
                "Key must be at least 5 characters and end in four letters, "
                "numbers, underscores, or hyphens."
            )
        return value

    @field_validator("label")
    @classmethod
    def validate_label_length(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 100:
            raise ValueError("Label must be 100 characters or fewer.")
        return value

    @model_validator(mode="after")
    def reject_key_in_label(self) -> ProviderKeyAdd:
        if self.label is not None and self.key in self.label:
            raise ValueError("Label must not contain the provider key.")
        return self


class ProviderKey(BaseModel):
    id: UUID
    provider: Provider
    label: str | None = Field(repr=False)
    key_hint: str = Field(repr=False)
    is_active: bool
    is_valid: bool | None
    last_validated_at: datetime | None
    last_validation_error: Literal["INVALID_CREDENTIAL"] | None
    cleanup_state: ProviderKeyLifecycle
    created_at: datetime


class ProviderKeyListResponse(BaseModel):
    keys: list[ProviderKey]


class ProviderKeyValidationResponse(BaseModel):
    outcome: ProviderValidationOutcome
    attempted_at: datetime
    code: ProviderValidationCode
    message: str
    key: ProviderKey


IdempotencyKey = UUID
