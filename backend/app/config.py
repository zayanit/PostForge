from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class Settings:
    supabase_url: str
    supabase_secret_key: str
    supabase_jwt_secret: str
    database_url: str | None = None


def load_settings() -> Settings:
    return Settings(
        supabase_url=os.environ["SUPABASE_URL"],
        supabase_secret_key=os.environ["SUPABASE_SECRET_KEY"],
        supabase_jwt_secret=os.environ["SUPABASE_JWT_SECRET"],
        database_url=os.getenv("DATABASE_URL"),
    )
