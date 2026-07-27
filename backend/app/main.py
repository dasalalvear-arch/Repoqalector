from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import repos, search
from app.core.config import settings
from app.core.database import Base, engine
from app.models import chunk  # noqa: F401  — registra CodeChunk antes de create_all

# pgvector: la extension tiene que existir antes de que create_all vea la
# columna Vector, o el CREATE TABLE falla con "type vector does not exist".
with engine.begin() as connection:
    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.project_name, version="0.1.0")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Defense-in-depth: la API solo devuelve JSON, nunca HTML navegable.
    Estos headers evitan sniffing de contenido, embedding en iframes y
    fuga de Referer hacia terceros."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response


app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(repos.router, prefix="/repos", tags=["repos"])
app.include_router(search.router, prefix="/search", tags=["search"])


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
