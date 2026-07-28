from dataclasses import dataclass
from functools import lru_cache
import os
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


_DEFAULT_ALLOWED_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
_DATABASE_TIMEOUT_SECONDS = 2
_DATABASE_TIMEOUT_MILLISECONDS = _DATABASE_TIMEOUT_SECONDS * 1000


@dataclass(frozen=True, slots=True, repr=False)
class Settings:
    supabase_url: str
    supabase_secret_key: str
    supabase_jwt_secret: str
    database_url: str | None = None
    allowed_origins: tuple[str, ...] = ()

    def __repr__(self) -> str:
        return "<Settings redacted>"


def load_settings() -> Settings:
    origins = os.getenv("ALLOWED_ORIGINS", _DEFAULT_ALLOWED_ORIGINS)
    return Settings(
        supabase_url=os.environ["SUPABASE_URL"],
        supabase_secret_key=os.environ["SUPABASE_SECRET_KEY"],
        supabase_jwt_secret=os.environ["SUPABASE_JWT_SECRET"],
        database_url=os.getenv("DATABASE_URL"),
        allowed_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = load_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")

    return create_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,
        hide_parameters=True,
        pool_timeout=_DATABASE_TIMEOUT_SECONDS,
        connect_args={
            "connect_timeout": _DATABASE_TIMEOUT_SECONDS,
            "options": (
                f"-c statement_timeout={_DATABASE_TIMEOUT_MILLISECONDS} "
                f"-c lock_timeout={_DATABASE_TIMEOUT_MILLISECONDS}"
            ),
        },
    )


_DATABASE_ROLE_PRIVILEGES = text(
    """
    SELECT
      current_user::text AS role_name,
      roles.rolsuper AS is_superuser,
      current_user NOT IN ('anon', 'authenticated', 'service_role') AS role_is_private,
      roles.rolsuper OR roles.rolbypassrls AS can_bypass_forced_rls,
      has_table_privilege(current_user, 'public.brands', 'SELECT')
        AND has_table_privilege(current_user, 'public.brands', 'INSERT')
        AND has_table_privilege(current_user, 'public.brands', 'UPDATE')
        AND has_table_privilege(current_user, 'public.brands', 'DELETE')
        AND has_table_privilege(current_user, 'public.provider_keys', 'SELECT')
        AND has_table_privilege(current_user, 'public.provider_keys', 'INSERT')
        AND has_table_privilege(current_user, 'public.provider_keys', 'UPDATE')
        AND has_table_privilege(current_user, 'public.provider_keys', 'DELETE')
        AND has_table_privilege(current_user, 'public.provider_key_idempotency', 'SELECT')
        AND has_table_privilege(current_user, 'public.provider_key_idempotency', 'INSERT')
        AND has_table_privilege(current_user, 'public.provider_key_idempotency', 'UPDATE')
        AND has_table_privilege(current_user, 'public.provider_key_idempotency', 'DELETE')
        AND has_table_privilege(current_user, 'public.brand_asset_operations', 'SELECT')
        AND has_table_privilege(current_user, 'public.brand_asset_operations', 'INSERT')
        AND has_table_privilege(current_user, 'public.brand_asset_operations', 'UPDATE')
        AND has_table_privilege(current_user, 'public.brand_asset_operations', 'DELETE')
        AS application_dml,
      has_schema_privilege(current_user, 'vault', 'USAGE') AS vault_schema_usage,
      has_function_privilege(
        current_user,
        to_regprocedure('vault.create_secret(text,text,text,uuid)'),
        'EXECUTE'
      ) AS vault_create,
      has_column_privilege(current_user, 'vault.decrypted_secrets', 'id', 'SELECT')
        AND has_column_privilege(
          current_user, 'vault.decrypted_secrets', 'decrypted_secret', 'SELECT'
        ) AS vault_decrypt,
      has_column_privilege(current_user, 'vault.secrets', 'id', 'SELECT')
        AS vault_secret_select,
      has_table_privilege(current_user, 'vault.secrets', 'DELETE')
        AS vault_secret_delete,
      (
        NOT has_schema_privilege(current_user, 'vault', 'CREATE')
        AND NOT has_function_privilege(
          current_user,
          to_regprocedure('vault.update_secret(uuid,text,text,text,uuid)'),
          'EXECUTE'
        )
        AND NOT has_table_privilege(
          current_user, 'vault.decrypted_secrets', 'SELECT'
        )
        AND NOT has_table_privilege(current_user, 'vault.secrets', 'SELECT')
      ) AS vault_least_privilege
    FROM pg_roles AS roles
    WHERE roles.rolname = current_user
    """
)


def assert_database_role_privileges() -> None:
    settings = load_settings()
    with get_engine().connect() as connection:
        privileges = dict(connection.execute(_DATABASE_ROLE_PRIVILEGES).mappings().one())

    role_name = privileges.pop("role_name")
    is_superuser = privileges.pop("is_superuser")
    vault_least_privilege = privileges.pop("vault_least_privilege")
    hostname = urlparse(settings.database_url).hostname
    local_postgres = role_name == "postgres" and hostname in {
        "127.0.0.1",
        "localhost",
        "::1",
    }
    role_is_acceptable = local_postgres or (
        not is_superuser and vault_least_privilege
    )

    if not role_is_acceptable or not all(privileges.values()):
        raise RuntimeError("database role lacks required backend privileges")
