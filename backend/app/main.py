from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import auth, categories, chat, items, matches, users, admin
from app.core.config import settings
from app.core.database import Base, engine, SessionLocal
from app.core.limiter import limiter
from app.services.schema import ensure_runtime_schema
from app.services.seed import create_admin, ensure_default_categories

Base.metadata.create_all(bind=engine)
ensure_runtime_schema(engine)

db = SessionLocal()
try:
    create_admin()
    ensure_default_categories(db)
finally:
    db.close()

app = FastAPI(title=settings.project_name, version="0.1.0")

# Rate limiting global (slowapi). Las rutas sensibles se decoran con
# @limiter.limit(...). Una peticion sobre el limite devuelve 429.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


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

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(items.router, prefix="/items", tags=["items"])
app.include_router(categories.router, prefix="/categories", tags=["categories"])
app.include_router(matches.router, prefix="/matches", tags=["matches"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])

@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
