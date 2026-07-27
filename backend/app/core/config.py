from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "U-Swap API"
    database_url: str = "postgresql+psycopg://uswap:uswap@localhost:5432/uswap"
    # Obligatorio y sin default: si no se define JWT_SECRET_KEY en el entorno,
    # la app falla al arrancar en vez de firmar tokens con una clave conocida.
    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    cors_origins: list[str] = ["http://localhost:5173"]

    # Admin sembrado al arrancar. Si admin_email/admin_password estan vacios,
    # no se crea ningun admin (la app funciona igual, sin panel disponible).
    admin_email: str | None = None
    admin_password: str | None = None
    admin_name: str = "Administrador U-Swap"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
