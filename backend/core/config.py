from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # asyncpg driver — note the +asyncpg, not psycopg2 (AniDex uses sync
    # psycopg2; this project's stack is async SQLAlchemy throughout).
    database_url: str
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
