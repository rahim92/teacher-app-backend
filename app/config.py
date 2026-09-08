from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central app configuration.

    DATABASE_URL defaults to a local SQLite file so the backend runs with zero
    external setup during development. In production, point it at PostgreSQL:
        postgresql+psycopg2://user:password@host:5432/dbname
    """

    app_name: str = "Middle School Teacher App API"
    database_url: str = "sqlite:///./app.db"
    secret_key: str = "change-me-in-production-please"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days: teachers rarely re-login
    redis_url: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
