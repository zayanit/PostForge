from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from ..config import get_engine
from ..models.brand_kit import BrandKit, BrandKitAnswers, BrandKitUpsert, KitStatus
from .brand_store import BrandNameTakenError, BrandStore


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

    @staticmethod
    def _empty_kit(brand: Mapping[str, Any]) -> BrandKit:
        return BrandKit(
            brand_id=brand["id"],
            brand_name=brand["name"],
            answers=BrandKitAnswers(),
            summary=None,
            status=KitStatus.NOT_STARTED,
            completed_at=None,
            updated_at=None,
        )

    @staticmethod
    def _kit_row(
        connection: Connection, brand_id: UUID
    ) -> Mapping[str, Any] | None:
        return connection.execute(
            text(
                """
            SELECT brand_id, tagline, tone, audience, colors, avoid_words,
                   summary, status, completed_at, updated_at
            FROM brand_kits
            WHERE brand_id = :brand_id
            """
            ),
            {"brand_id": brand_id},
        ).mappings().one_or_none()

    @staticmethod
    def _merged_answers(
        existing: Mapping[str, Any] | None,
        payload: BrandKitUpsert,
    ) -> BrandKitAnswers:
        current = {
            "tagline": existing["tagline"] if existing else None,
            "tone": existing["tone"] if existing else None,
            "audience": existing["audience"] if existing else None,
            "colors": list(existing["colors"] or []) if existing else [],
            "avoid_words": existing["avoid_words"] if existing else None,
        }
        current.update(payload.answers.model_dump(exclude_unset=True))
        return BrandKitAnswers.model_validate(current)

    @staticmethod
    def _has_saved_answer(answers: BrandKitAnswers) -> bool:
        return any(
            (
                answers.tagline,
                answers.tone,
                answers.audience,
                answers.colors,
                answers.avoid_words,
            )
        )

    def get_kit(self, user_id: str, brand_id: UUID) -> BrandKit:
        with self.engine.begin() as connection:
            brand = BrandStore.lock_owned_brand(connection, user_id, brand_id)
            BrandStore.require_normal_brand(brand)
            row = self._kit_row(connection, brand_id)
            if row is None:
                return self._empty_kit(brand)
            return self._to_brand_kit({"brand_name": brand["name"], **row})

    def upsert_kit(
        self,
        user_id: str,
        brand_id: UUID,
        payload: BrandKitUpsert,
    ) -> BrandKit:
        try:
            with self.engine.begin() as connection:
                brand = BrandStore.lock_owned_brand(connection, user_id, brand_id)
                BrandStore.require_normal_brand(brand)
                existing = self._kit_row(connection, brand_id)
                answers = self._merged_answers(existing, payload)
                complete = (
                    answers.tone is not None
                    and answers.audience is not None
                    and bool(answers.colors)
                )
                status = KitStatus.COMPLETE if complete else (
                    KitStatus.IN_PROGRESS if self._has_saved_answer(answers)
                    else KitStatus.NOT_STARTED
                )
                summary = derive_summary(payload.name, answers) if complete else None

                connection.execute(
                    text(
                        """
                    UPDATE brands
                    SET name = :name
                    WHERE id = :brand_id
                    """
                    ),
                    {"brand_id": brand_id, "name": payload.name},
                )
                connection.execute(
                    text(
                        """
                    INSERT INTO brand_kits (
                        brand_id, tagline, tone, audience, colors, avoid_words,
                        summary, status, completed_at
                    ) VALUES (
                        :brand_id, :tagline, CAST(:tone AS public.tone_t), :audience,
                        :colors, :avoid_words, :summary,
                        CAST(:status AS public.kit_status_t),
                        CASE WHEN :status = 'complete' THEN now() ELSE NULL END
                    )
                    ON CONFLICT (brand_id) DO UPDATE SET
                        tagline = EXCLUDED.tagline,
                        tone = EXCLUDED.tone,
                        audience = EXCLUDED.audience,
                        colors = EXCLUDED.colors,
                        avoid_words = EXCLUDED.avoid_words,
                        summary = EXCLUDED.summary,
                        status = EXCLUDED.status,
                        completed_at = CASE
                            WHEN brand_kits.status = 'complete'
                                 AND EXCLUDED.status = 'complete'
                            THEN brand_kits.completed_at
                            ELSE EXCLUDED.completed_at
                        END
                    """
                    ),
                    {
                        "brand_id": brand_id,
                        "tagline": answers.tagline,
                        "tone": answers.tone.value if answers.tone else None,
                        "audience": answers.audience,
                        "colors": answers.colors,
                        "avoid_words": answers.avoid_words,
                        "summary": summary,
                        "status": status.value,
                    },
                )
                row = self._kit_row(connection, brand_id)
                assert row is not None
                updated_brand_name = payload.name
                return self._to_brand_kit(
                    {"brand_name": updated_brand_name, **row}
                )
        except IntegrityError as exc:
            original = exc.orig
            constraint_name = getattr(
                getattr(original, "diag", None), "constraint_name", None
            )
            if (
                getattr(original, "pgcode", None) == "23505"
                and constraint_name == "uq_brands_owner_name_ci"
            ):
                raise BrandNameTakenError from exc
            raise


@lru_cache(maxsize=1)
def get_brand_kit_store() -> BrandKitStore:
    return BrandKitStore(get_engine())
