from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Engine

from ..config import get_engine
from ..models.brand_kit import BrandKit, BrandKitAnswers, BrandKitUpsert
from .brand_store import BrandStore


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def derive_summary(
    brand_name: str,
    answers: BrandKitAnswers | Mapping[str, Any],
) -> str:
    normalized_answers = BrandKitAnswers.model_validate(answers)
    normalized_name = _collapse_whitespace(brand_name)
    audience = (
        _collapse_whitespace(normalized_answers.audience)
        if normalized_answers.audience is not None
        else ""
    )
    if not normalized_name or normalized_answers.tone is None or not audience:
        raise ValueError("A summary requires complete brand kit answers.")
    if not normalized_answers.colors:
        raise ValueError("A summary requires complete brand kit answers.")

    tagline = (
        _collapse_whitespace(normalized_answers.tagline)
        if normalized_answers.tagline is not None
        else "None specified"
    )
    avoid_words = (
        _collapse_whitespace(normalized_answers.avoid_words)
        if normalized_answers.avoid_words is not None
        else "None specified"
    )
    return "\n".join(
        (
            f"Brand: {normalized_name}",
            f"Tagline: {tagline}",
            f"Tone: {normalized_answers.tone.value}",
            f"Audience: {audience}",
            f"Colors: {', '.join(normalized_answers.colors)}",
            f"Avoid words: {avoid_words}",
        )
    )


@dataclass(frozen=True, slots=True)
class BrandKitStore:
    engine: Engine

    @staticmethod
    def _to_brand_kit(row: Mapping[str, Any]) -> BrandKit:
        return BrandKit.model_validate(
            {
                "brand_id": row["brand_id"],
                "brand_name": row["brand_name"],
                "answers": {
                    "tagline": row["tagline"],
                    "tone": row["tone"],
                    "audience": row["audience"],
                    "colors": row["colors"],
                    "avoid_words": row["avoid_words"],
                },
                "summary": row["summary"],
                "status": row["status"],
                "completed_at": row["completed_at"],
                "updated_at": row["updated_at"],
            }
        )

    def get_kit(self, user_id: str, brand_id: UUID) -> BrandKit:
        with self.engine.begin() as connection:
            brand = BrandStore.lock_owned_brand(connection, user_id, brand_id)
            BrandStore.require_normal_brand(brand)
            raise NotImplementedError("Brand kit reads are implemented in T018.")

    def upsert_kit(
        self,
        user_id: str,
        brand_id: UUID,
        payload: BrandKitUpsert,
    ) -> BrandKit:
        with self.engine.begin() as connection:
            brand = BrandStore.lock_owned_brand(connection, user_id, brand_id)
            BrandStore.require_normal_brand(brand)
            raise NotImplementedError("Brand kit persistence is implemented in T019.")


@lru_cache(maxsize=1)
def get_brand_kit_store() -> BrandKitStore:
    return BrandKitStore(get_engine())
