from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # asyncpg driver — note the +asyncpg, not psycopg2 (AniDex uses sync
    # psycopg2; this project's stack is async SQLAlchemy throughout).
    database_url: str
    environment: str = "development"

    # Outbox worker (#9) — how often it polls when there's nothing to do.
    # Not a message broker's push latency; a few seconds is fine for
    # moderator notifications / cache purges, per CLAUDE.md Architecture.
    worker_poll_interval_seconds: int = 5
    worker_batch_size: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
