from dataclasses import dataclass
import os


_DEFAULT_ALLOWED_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


@dataclass(frozen=True, slots=True)
class Settings:
    supabase_url: str
    supabase_secret_key: str
    supabase_jwt_secret: str
    database_url: str | None = None
    allowed_origins: tuple[str, ...] = ()


def load_settings() -> Settings:
    origins = os.getenv("ALLOWED_ORIGINS", _DEFAULT_ALLOWED_ORIGINS)
    return Settings(
        supabase_url=os.environ["SUPABASE_URL"],
        supabase_secret_key=os.environ["SUPABASE_SECRET_KEY"],
        supabase_jwt_secret=os.environ["SUPABASE_JWT_SECRET"],
        database_url=os.getenv("DATABASE_URL"),
        allowed_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
    )
