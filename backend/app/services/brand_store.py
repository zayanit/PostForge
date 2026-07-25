from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from ..config import get_engine
from ..models.brand import Brand, BrandCreate


class BrandNameTakenError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class BrandStore:
    engine: Engine

    def create_brand(self, user_id: str, payload: BrandCreate) -> Brand:
        try:
            with self.engine.begin() as connection:
                row = connection.execute(
                    text(
                        """
                        INSERT INTO brands (owner_user_id, name)
                        VALUES (:owner_user_id, :name)
                        RETURNING id, name, created_at
                        """
                    ),
                    {"owner_user_id": user_id, "name": payload.name},
                ).mappings().one()
        except IntegrityError as exc:
            original = exc.orig
            constraint_name = getattr(getattr(original, "diag", None), "constraint_name", None)
            if getattr(original, "pgcode", None) == "23505" and constraint_name == "uq_brands_owner_name_ci":
                raise BrandNameTakenError from exc
            raise

        return Brand.model_validate({"logo_url": None, **row})


@lru_cache(maxsize=1)
def get_brand_store() -> BrandStore:
    return BrandStore(get_engine())
