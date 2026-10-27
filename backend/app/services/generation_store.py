from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..config import get_engine
from ..models.generation import GenerateRequest
from ..presets import PRESETS
from .brand_store import BrandStore


class GenerationConflict(Exception):
    def __init__(self, code: str):
        self.code = code


@contextmanager
def generation_asset_guard(engine: Engine, brand_id: UUID):
    """Transaction lock for publication/deletion, never held during provider calls."""
    with engine.begin() as connection:
        locked = connection.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:brand, 19))"),
            {"brand": str(brand_id)},
        ).scalar_one()
        if not locked:
            raise GenerationConflict("GENERATION_ASSET_BUSY")
        # Transaction scope also works with transaction-pooling database proxies.
        # No row lock is retained while Storage is contacted.
        yield


@dataclass(frozen=True)
class GenerationStore:
    engine: Engine

    def submit(
        self, owner: str, brand_id: UUID, payload: GenerateRequest, request_id: UUID
    ):
        digest = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
        with self.engine.begin() as connection:
            brand = BrandStore.lock_owned_brand(connection, owner, brand_id)
            BrandStore.require_normal_brand(brand)
            existing = (
                connection.execute(
                    text(
                        "SELECT * FROM generations WHERE brand_id=:brand AND "
                        "request_id=:request"
                    ),
                    {"brand": brand_id, "request": request_id},
                )
                .mappings()
                .one_or_none()
            )
            if existing:
                if existing["request_hash"] != digest:
                    raise GenerationConflict("IDEMPOTENCY_CONFLICT")
                return dict(existing)
            key = connection.execute(
                text(
                    "SELECT id FROM provider_keys WHERE brand_id=:brand "
                    "AND provider='openai' AND is_active AND lifecycle='normal' "
                    "AND is_valid IS DISTINCT FROM false"
                ),
                {"brand": brand_id},
            ).scalar_one_or_none()
            if key is None:
                raise GenerationConflict("OPENAI_KEY_REQUIRED")
            kit = (
                connection.execute(
                    text(
                        "SELECT tagline, tone, audience, colors, avoid_words "
                        "FROM brand_kits WHERE brand_id=:brand"
                    ),
                    {"brand": brand_id},
                )
                .mappings()
                .one_or_none()
            )
            context = "Brand: " + brand["name"]
            if kit:
                context += "\n" + json.dumps(dict(kit), ensure_ascii=False, default=str)
            width, height, _ = PRESETS[payload.platform_preset]
            row = (
                connection.execute(
                    text("""
                INSERT INTO generations (id, brand_id, request_id, request_hash,
                prompt, context_snapshot, provider_key_id, platform_preset, width,
                height) VALUES
                (:id,:brand,:request,:digest,:prompt,:context,:key,:preset,:width,:height)
                RETURNING *
            """),
                    {
                        "id": uuid4(),
                        "brand": brand_id,
                        "request": request_id,
                        "digest": digest,
                        "prompt": payload.prompt,
                        "context": context,
                        "key": key,
                        "preset": payload.platform_preset,
                        "width": width,
                        "height": height,
                    },
                )
                .mappings()
                .one()
            )
            return dict(row)

    def list(
        self,
        owner: str,
        brand_id: UUID,
        page: int,
        per_page: int,
        provider=None,
        status=None,
    ):
        with self.engine.begin() as connection:
            BrandStore.lock_owned_brand(connection, owner, brand_id)
            params = {
                "brand": brand_id,
                "limit": per_page,
                "offset": (page - 1) * per_page,
            }
            where = "brand_id=:brand"
            if provider:
                where += " AND provider=CAST(:provider AS provider_t)"
                params["provider"] = provider
            if status:
                where += " AND status=:status"
                params["status"] = status
            total = connection.execute(
                text(f"SELECT count(*) FROM generations WHERE {where}"), params
            ).scalar_one()
            rows = (
                connection.execute(
                    text(
                        f"SELECT * FROM generations WHERE {where} "
                        "ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset"
                    ),
                    params,
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows], total

    def get(self, owner: str, brand_id: UUID, generation_id: UUID):
        with self.engine.begin() as connection:
            BrandStore.lock_owned_brand(connection, owner, brand_id)
            row = (
                connection.execute(
                    text("SELECT * FROM generations WHERE brand_id=:brand AND id=:id"),
                    {"brand": brand_id, "id": generation_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise LookupError
            return dict(row)

    def fence_delete(self, owner: str, brand_id: UUID, generation_id: UUID):
        with self.engine.begin() as connection:
            BrandStore.lock_owned_brand(connection, owner, brand_id)
            row = (
                connection.execute(
                    text(
                        "SELECT * FROM generations WHERE brand_id=:brand AND "
                        "id=:id FOR UPDATE"
                    ),
                    {"brand": brand_id, "id": generation_id},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise LookupError
            if row["status"] == "processing":
                raise GenerationConflict("GENERATION_PROCESSING")
            connection.execute(
                text("UPDATE generations SET cleanup_required=true WHERE id=:id"),
                {"id": generation_id},
            )

    def finish_delete(self, owner: str, brand_id: UUID, generation_id: UUID):
        with self.engine.begin() as connection:
            BrandStore.lock_owned_brand(connection, owner, brand_id)
            connection.execute(
                text(
                    "DELETE FROM generations WHERE id=:id AND brand_id=:brand"
                    " AND cleanup_required"
                ),
                {"id": generation_id, "brand": brand_id},
            )

    def claim(self):
        # Lock brands before jobs for submission, deletion, and claims. Brands are
        # ordered by their oldest claimable job so one busy brand cannot starve others.
        with self.engine.begin() as connection:
            candidate = connection.execute(text("""
                SELECT b.id FROM brands b WHERE b.deletion_state='active' AND EXISTS
                ( SELECT 1 FROM generations g WHERE g.brand_id=b.id AND NOT
                g.cleanup_required AND (g.status='pending' OR (g.status='processing'
                AND g.lease_expires_at < clock_timestamp())) ) ORDER BY ( SELECT
                min(g.created_at) FROM generations g WHERE g.brand_id=b.id AND NOT
                g.cleanup_required AND (g.status='pending' OR (g.status='processing'
                AND g.lease_expires_at < clock_timestamp())) ), b.id
                FOR UPDATE OF b SKIP LOCKED LIMIT 1
            """)).scalar_one_or_none()
            if candidate is None:
                return None
            row = (
                connection.execute(
                    text("""
                SELECT * FROM generations WHERE brand_id=:brand AND NOT
                cleanup_required AND (status='pending' OR (status='processing' AND
                lease_expires_at < clock_timestamp())) ORDER BY created_at,id FOR
                UPDATE SKIP LOCKED LIMIT 1
            """),
                    {"brand": candidate},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            token = uuid4()
            connection.execute(
                text("""
                UPDATE generations SET status='processing',lease_token=:token,
                lease_expires_at=clock_timestamp()+interval '5 minutes' WHERE id=:id
            """),
                {"id": row["id"], "token": token},
            )
            return {
                **dict(row),
                "recovery": row["status"] == "processing",
                "lease_token": token,
            }

    def heartbeat(self, job) -> bool:
        with self.engine.begin() as connection:
            return bool(
                connection.execute(
                    text("""
                UPDATE generations SET lease_expires_at=clock_timestamp()+interval
                '5 minutes' WHERE id=:id AND lease_token=:token AND
                status='processing' AND lease_expires_at > clock_timestamp() AND NOT
                cleanup_required AND EXISTS (SELECT 1 FROM brands b WHERE
                b.id=brand_id AND b.deletion_state='active')
            """),
                    {"id": job["id"], "token": job["lease_token"]},
                ).rowcount
            )

    def usable(self, job) -> bool:
        with self.engine.connect() as connection:
            return bool(
                connection.execute(
                    text("""
                SELECT EXISTS (SELECT 1 FROM generations g JOIN brands b ON
                b.id=g.brand_id WHERE g.id=:id AND g.lease_token=:token AND
                g.status='processing' AND g.lease_expires_at > clock_timestamp() AND
                NOT g.cleanup_required AND b.deletion_state='active')
            """),
                    {"id": job["id"], "token": job["lease_token"]},
                ).scalar_one()
            )

    def credential(self, job) -> str | None:
        with self.engine.connect() as connection:
            return connection.execute(
                text("""
                SELECT ds.decrypted_secret FROM provider_keys pk JOIN
                vault.decrypted_secrets ds ON ds.id=pk.vault_secret_id JOIN brands b
                ON b.id=pk.brand_id WHERE pk.id=:key AND pk.brand_id=:brand AND
                pk.provider='openai' AND pk.is_active AND pk.lifecycle='normal' AND
                pk.is_valid IS DISTINCT FROM false AND b.deletion_state='active'
            """),
                {"key": job["provider_key_id"], "brand": job["brand_id"]},
            ).scalar_one_or_none()

    def begin_upload(self, job) -> bool:
        with self.engine.begin() as connection:
            return bool(
                connection.execute(
                    text("""
                UPDATE generations SET upload_fence_until=clock_timestamp()+interval
                '5 minutes' WHERE id=:id AND lease_token=:token AND
                status='processing' AND lease_expires_at > clock_timestamp() AND
                EXISTS (SELECT 1 FROM brands b WHERE b.id=brand_id AND
                b.deletion_state='active')
            """),
                    {"id": job["id"], "token": job["lease_token"]},
                ).rowcount
            )

    def finish(self, job, *, path=None, error=None, provider_request_id=None) -> bool:
        with self.engine.begin() as connection:
            return bool(
                connection.execute(
                    text("""
                UPDATE generations SET
                status=:status,image_path=:path,error_code=:error,
                completed_at=clock_timestamp(),lease_token=NULL,lease_expires_at=NULL,upload_fence_until=NULL,
                provider_request_id=:provider_request_id WHERE id=:id AND
                lease_token=:token AND status='processing' AND lease_expires_at >
                clock_timestamp() AND EXISTS (SELECT 1 FROM brands b WHERE
                b.id=brand_id AND b.deletion_state='active')
            """),
                    {
                        "id": job["id"],
                        "token": job["lease_token"],
                        "path": path,
                        "status": "failed" if error else "succeeded",
                        "error": error,
                        "provider_request_id": provider_request_id,
                    },
                ).rowcount
            )


@lru_cache(maxsize=1)
def get_generation_store() -> GenerationStore:
    return GenerationStore(get_engine())
