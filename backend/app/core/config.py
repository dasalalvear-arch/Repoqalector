from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    project_name: str = "RepoQA API"
    database_url: str = "postgresql+psycopg://repoqa:repoqa@localhost:5432/repoqa"
    cors_origins: list[str] = ["http://localhost:5173"]

    # Directorio donde se clonan los repos a indexar. Efimero a proposito:
    # lo unico que persiste es lo que queda en la tabla code_chunks.
    clone_dir: str = "/tmp/repoqa-clones"

    # Gemini responde /ask. Se usa su endpoint compatible con el formato de
    # OpenAI para que un solo cliente sirva tambien al juez. La key llega por
    # variable de entorno desde el .env de la raiz; vacia = /ask devuelve 503,
    # pero /search y /repos siguen funcionando.
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    # 2.5-flash ya no se ofrece a keys nuevas (404); 3.8-flash daba 503 por
    # demanda al implementar. Se cambia aqui o en .env.example.
    gemini_model: str = "gemini-3.5-flash"

    # Juez de fundamentacion: solo lo usa evaluate_ask.py. Cualquier proveedor
    # con endpoint compatible con OpenAI (Groq, Together, OpenRouter).
    judge_api_key: str = ""
    judge_base_url: str = "https://api.groq.com/openai/v1"
    # Groq retiro llama-3.3-70b; gpt-oss-120b es el mas capaz que ofrece y no
    # es de la familia de Gemini, asi que no se juzga a si mismo.
    judge_model: str = "openai/gpt-oss-120b"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
