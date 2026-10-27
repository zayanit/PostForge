"""Real PostgreSQL queue/RLS tests; Supabase Auth/Vault/Storage are minimal test
scaffolds.

Install optional `embedded-postgres` to run without Docker. Never connects to
user databases.
"""

import asyncio
import os
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from backend.app.models.generation import GenerateRequest
from backend.app.services.generation_store import (
    GenerationConflict,
    GenerationStore,
    generation_asset_guard,
)
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


@contextmanager
def isolated_postgres(data):
    embedded = pytest.importorskip(
        "embedded_postgres",
        reason="Install embedded-postgres for isolated PostgreSQL queue tests",
    )
    if os.name != "nt":
        with embedded.get_server(data) as server:
            yield server.get_uri()
        return
    # Start postgres directly on Windows: pg_ctl's restricted-token launcher is not
    # supported inside some Windows sandboxes. This runs as the current user.
    binary = Path(embedded.__file__).parent / "pginstall" / "bin"
    subprocess.run(
        [str(binary / "initdb.exe"), "-D", str(data), "-U", "postgres", "-A", "trust"],
        check=True,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (data / "test-server.log").open("w") as log:
        process = subprocess.Popen(
            [
                str(binary / "postgres.exe"),
                "-D",
                str(data),
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
            ],
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        uri = f"postgresql://postgres@127.0.0.1:{port}/postgres"
        probe = create_engine(uri)
        try:
            for _ in range(100):
                try:
                    with probe.connect():
                        break
                except Exception:
                    if process.poll() is not None:
                        raise RuntimeError("Test PostgreSQL failed to start") from None
                    time.sleep(0.1)
            else:
                raise RuntimeError("Test PostgreSQL startup timed out")
            probe.dispose()
            yield uri
        finally:
            probe.dispose()
            subprocess.run(
                [
                    str(binary / "pg_ctl.exe"),
                    "-D",
                    str(data),
                    "-m",
                    "fast",
                    "-w",
                    "stop",
                ],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=15,
            )
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=15)


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    data = tmp_path_factory.mktemp("postforge-postgres") / "data"
    with isolated_postgres(data) as uri:
        engine = create_engine(uri, pool_size=8, hide_parameters=True)
        with engine.begin() as connection:
            connection.exec_driver_sql("""
                CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE
                service_role BYPASSRLS; CREATE SCHEMA private; CREATE SCHEMA
                storage; CREATE SCHEMA vault; CREATE TYPE provider_t AS ENUM
                ('openai','gemini'); CREATE TABLE brands (id uuid PRIMARY
                KEY,owner_user_id uuid,name text, deletion_state text DEFAULT
                'active' ,logo_path text,created_at timestamptz DEFAULT now());
                CREATE TABLE brand_kits (brand_id uuid PRIMARY KEY,tagline text,tone
                text,audience text, colors text[],avoid_words text,status text
                DEFAULT 'not_started' ); CREATE TABLE provider_keys (id uuid PRIMARY
                KEY,brand_id uuid REFERENCES brands(id), provider
                provider_t,is_active boolean,lifecycle text DEFAULT 'normal'
                ,is_valid boolean,vault_secret_id uuid, last_validated_at
                timestamptz,last_validation_error text,validation_token
                uuid,validation_lease_expires_at timestamptz); CREATE TABLE
                vault.decrypted_secrets (id uuid PRIMARY KEY,decrypted_secret text);
                CREATE TABLE vault.secrets (id uuid PRIMARY KEY); CREATE TABLE
                provider_key_idempotency (id uuid,brand_id uuid); CREATE TABLE
                brand_asset_operations (id uuid,brand_id uuid); CREATE TABLE
                storage.buckets (id text PRIMARY KEY,name text,public
                boolean,file_size_limit bigint,allowed_mime_types text[]); CREATE
                FUNCTION private.is_brand_owner(brand uuid) RETURNS boolean LANGUAGE
                sql SECURITY DEFINER SET search_path='' AS $$ SELECT EXISTS (SELECT
                1 FROM public.brands WHERE id=brand AND
                owner_user_id=NULLIF(current_setting('request.jwt.claim.sub',true),'')::uuid)
                $$; GRANT USAGE ON SCHEMA private TO authenticated;
            """)
            migration = (
                Path(__file__).resolve().parents[3]
                / "supabase/migrations/00019_create_generations.sql"
            )
            connection.exec_driver_sql(migration.read_text())
        yield engine
        engine.dispose()


@pytest.fixture
def setup(engine):
    brand, owner, key, secret = uuid4(), uuid4(), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO brands(id,owner_user_id,name) VALUES (:brand,:ow"
                "ner,'Test brand')"
            ),
            dict(brand=brand, owner=owner),
        )
        connection.execute(
            text(
                "INSERT INTO provider_keys(id,brand_id,provider,is_active,vau"
                "lt_secret_id) VALUES (:key,:brand,'openai',true,:secret)"
            ),
            dict(key=key, brand=brand, secret=secret),
        )
        connection.execute(
            text("INSERT INTO vault.decrypted_secrets VALUES (:id,'test-only-secret')"),
            dict(id=secret),
        )
    store = GenerationStore(engine)
    yield store, str(owner), brand
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM generations WHERE brand_id=:brand"), dict(brand=brand)
        )
        connection.execute(
            text("DELETE FROM provider_keys WHERE brand_id=:brand"), dict(brand=brand)
        )
        connection.execute(
            text("DELETE FROM brand_kits WHERE brand_id=:brand"), dict(brand=brand)
        )
        connection.execute(
            text("DELETE FROM brands WHERE id=:brand"), dict(brand=brand)
        )
        connection.execute(
            text("DELETE FROM vault.decrypted_secrets WHERE id=:id"), dict(id=secret)
        )


def payload(prompt="First prompt"):
    return GenerateRequest(prompt=prompt, platform_preset="instagram_post")


def test_duplicate_submission_and_conflicting_reuse(setup):
    store, owner, brand = setup
    request = uuid4()
    with ThreadPoolExecutor(2) as executor:
        results = list(
            executor.map(
                lambda _: store.submit(owner, brand, payload(), request), range(2)
            )
        )
    assert results[0]["id"] == results[1]["id"]
    with pytest.raises(GenerationConflict, match="IDEMPOTENCY_CONFLICT"):
        store.submit(owner, brand, payload("Different prompt"), request)


def test_empty_and_partial_context_are_snapshotted(setup):
    store, owner, brand = setup
    first = store.submit(owner, brand, payload(), uuid4())
    assert first["context_snapshot"] == "Brand: Test brand"
    with store.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO brand_kits(brand_id,audience) VALUES (:brand,'Gardeners')"
            ),
            dict(brand=brand),
        )
    second = store.submit(owner, brand, payload(), uuid4())
    with store.engine.begin() as connection:
        connection.execute(
            text("UPDATE brand_kits SET audience='Changed' WHERE brand_id=:brand"),
            dict(brand=brand),
        )
    assert "Gardeners" in store.get(owner, brand, second["id"])["context_snapshot"]
    assert "Gardeners" not in first["context_snapshot"]


def test_complete_kit_context_is_snapshotted(setup):
    store, owner, brand = setup
    with store.engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO brand_kits
                (brand_id,tagline,tone,audience,colors,avoid_words,status)
            VALUES (:brand,'Grow together','professional','Gardeners',
                ARRAY['#00AA00'],'cheap','complete')
        """),
            {"brand": brand},
        )
    row = store.submit(owner, brand, payload(), uuid4())
    for answer in ("Grow together", "professional", "Gardeners", "#00AA00", "cheap"):
        assert answer in row["context_snapshot"]


def test_atomic_claim_and_stale_lease_cannot_publish(setup):
    store, owner, brand = setup
    row = store.submit(owner, brand, payload(), uuid4())
    with ThreadPoolExecutor(2) as executor:
        jobs = list(executor.map(lambda _: store.claim(), range(2)))
    assert sum(job is not None for job in jobs) == 1
    original = next(job for job in jobs if job)
    assert original["recovery"] is False
    assert store.heartbeat(original)
    with store.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE generations SET lease_expires_at=now()-interval '1 se"
                "cond' WHERE id=:id"
            ),
            dict(id=row["id"]),
        )
    assert not store.heartbeat(original)
    recovered = store.claim()
    assert recovered["recovery"] is True
    assert recovered["lease_token"] != original["lease_token"]
    assert not store.finish(original, path="stale.png")
    assert store.finish(recovered, error="GENERATION_INTERRUPTED")


def test_processing_cannot_be_deleted_pending_can(setup):
    store, owner, brand = setup
    row = store.submit(owner, brand, payload(), uuid4())
    job = store.claim()
    with pytest.raises(GenerationConflict, match="GENERATION_PROCESSING"):
        store.fence_delete(owner, brand, row["id"])
    store.finish(job, error="PROVIDER_TIMEOUT")
    store.fence_delete(owner, brand, row["id"])
    store.finish_delete(owner, brand, row["id"])
    with pytest.raises(LookupError):
        store.get(owner, brand, row["id"])
    pending = store.submit(owner, brand, payload(), uuid4())
    store.fence_delete(owner, brand, pending["id"])
    assert store.claim() is None
    store.finish_delete(owner, brand, pending["id"])


def test_fenced_brand_and_stale_worker_never_publish(setup):
    store, owner, brand = setup
    store.submit(owner, brand, payload(), uuid4())
    job = store.claim()
    with store.engine.begin() as connection:
        connection.execute(
            text("UPDATE brands SET deletion_state='cleanup_required' WHERE id=:id"),
            dict(id=brand),
        )
    assert not store.usable(job)
    assert not store.heartbeat(job)
    assert not store.finish(job, path=f"brands/{brand}/generations/{job['id']}.png")
    assert store.claim() is None


def test_asset_guard_serializes_other_connections(setup):
    store, _, brand = setup
    with generation_asset_guard(store.engine, brand):
        with pytest.raises(GenerationConflict, match="GENERATION_ASSET_BUSY"):
            with generation_asset_guard(store.engine, brand):
                pass
    with generation_asset_guard(store.engine, brand):
        pass


def test_owner_checks_and_forced_rls_with_no_client_writes(setup):
    store, owner, brand = setup
    row = store.submit(owner, brand, payload(), uuid4())
    with pytest.raises(LookupError):
        store.get(str(uuid4()), brand, row["id"])
    with store.engine.begin() as connection:
        flags = connection.execute(
            text(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHER"
                "E oid='generations'::regclass"
            )
        ).one()
        assert flags == (True, True)
        connection.exec_driver_sql("SET LOCAL ROLE authenticated")
        connection.execute(
            text("SELECT set_config('request.jwt.claim.sub',:owner,true)"),
            dict(owner=owner),
        )
        assert (
            connection.execute(
                text("SELECT id FROM generations WHERE brand_id=:brand"),
                dict(brand=brand),
            ).scalar_one()
            == row["id"]
        )
        connection.execute(
            text("SELECT set_config('request.jwt.claim.sub',:owner,true)"),
            dict(owner=str(uuid4())),
        )
        assert (
            connection.execute(
                text("SELECT id FROM generations WHERE brand_id=:brand"),
                dict(brand=brand),
            ).first()
            is None
        )
    for command in (
        "UPDATE generations SET prompt='hacked'",
        "DELETE FROM generations",
    ):
        with pytest.raises(DBAPIError):
            with store.engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL ROLE authenticated")
                connection.exec_driver_sql(command)


def test_private_bucket_migration_and_missing_revoked_key(setup):
    store, owner, brand = setup
    row = store.submit(owner, brand, payload(), uuid4())
    job = store.claim()
    assert store.credential(job) == "test-only-secret"
    with store.engine.begin() as connection:
        assert (
            connection.execute(
                text("SELECT public FROM storage.buckets WHERE id='generation-assets'")
            ).scalar_one()
            is False
        )
        connection.execute(
            text("UPDATE provider_keys SET is_active=false WHERE brand_id=:brand"),
            dict(brand=brand),
        )
    assert store.credential(job) is None
    with pytest.raises(GenerationConflict, match="OPENAI_KEY_REQUIRED"):
        store.submit(owner, brand, payload(), uuid4())
    # Replays still resolve after key removal and do not create paid work.
    assert store.submit(owner, brand, payload(), row["request_id"])["id"] == row["id"]


def test_real_worker_publication_history_and_physical_brand_cleanup(setup):
    from backend.app.services.brand_deletion import BrandDeletion
    from backend.app.services.brand_store import BrandStore
    from backend.app.worker import process_job

    store, owner, brand = setup

    class Storage:
        def __init__(self):
            self.objects = {}

        def path(self, brand, generation):
            return f"brands/{brand}/generations/{generation}.png"

        async def upload(self, path, data):
            self.objects[path] = data

        async def object_exists(self, path):
            return path in self.objects

        async def delete_brand_prefix(self, brand):
            self.objects.clear()

        async def brand_prefix_is_empty(self, brand):
            return not self.objects

    storage, logos = Storage(), Storage()

    async def provider(job, key):
        assert key == "test-only-secret"
        assert job["context_snapshot"] == "Brand: Test brand"
        return b"test-png", "safe-provider-request-id"

    row = store.submit(owner, brand, payload(), uuid4())
    asyncio.run(process_job(store, storage, store.claim(), provider))
    saved = store.get(owner, brand, row["id"])
    assert saved["status"] == "succeeded"
    assert saved["image_path"] in storage.objects
    assert saved["upload_fence_until"] is None
    assert store.list(owner, brand, 1, 20)[1] == 1
    deletion = BrandDeletion(store.engine, BrandStore(store.engine), logos, storage)
    asyncio.run(deletion.delete(owner, brand, "Test brand"))
    assert not storage.objects
    with store.engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM generations WHERE id=:id"),
                dict(id=row["id"]),
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM brands WHERE id=:id"), dict(id=brand)
            ).scalar_one()
            == 0
        )


def test_uncertain_upload_blocks_brand_deletion_and_late_publication(setup):
    from backend.app.services.brand_deletion import (
        BrandDeletion,
        BrandDeletionCleanupError,
    )
    from backend.app.services.brand_store import BrandStore

    store, owner, brand = setup
    store.submit(owner, brand, payload(), uuid4())
    job = store.claim()
    assert store.begin_upload(job)

    class Storage:
        async def delete_brand_prefix(self, *_):
            pytest.fail("Must retain fence during uncertain upload")

    deletion = BrandDeletion(
        store.engine, BrandStore(store.engine), Storage(), Storage()
    )
    with pytest.raises(BrandDeletionCleanupError):
        asyncio.run(deletion.delete(owner, brand, "Test brand"))
    assert not store.usable(job)
    assert not store.finish(job, path=f"brands/{brand}/generations/{job['id']}.png")
