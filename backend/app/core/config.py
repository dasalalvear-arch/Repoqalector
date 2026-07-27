from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "RepoQA API"
    database_url: str = "postgresql+psycopg://repoqa:repoqa@localhost:5432/repoqa"
    cors_origins: list[str] = ["http://localhost:5173"]

    # Directorio donde se clonan los repos a indexar. Efimero a proposito:
    # lo unico que persiste es lo que queda en la tabla code_chunks.
    clone_dir: str = "/tmp/repoqa-clones"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
