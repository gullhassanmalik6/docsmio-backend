from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+pysqlite:///./docsmio.db"
    secret_key: str = "replace-with-a-long-random-string"
    access_token_minutes: int = 60
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    cookie_secure: bool = False
    cookie_name: str = "docsmio_session"
    library_storage_dir: str = "./storage"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


PLACEHOLDER_SECRETS = {"replace-with-a-long-random-string", "change-me"}


def secret_is_usable(value: str) -> bool:
    return len(value) >= 24 and value not in PLACEHOLDER_SECRETS


@lru_cache
def get_settings() -> Settings:
    return Settings()
