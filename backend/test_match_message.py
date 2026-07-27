"""Smoke test for the mandatory-message request rule (spec 2026-07-07).

No framework. Uses in-memory SQLite so it needs no Postgres/psycopg. Run inside
Docker or a venv where the app deps are installed:

    cd backend
    JWT_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx python test_match_message.py
"""
import os

os.environ.setdefault("JWT_SECRET_KEY", "x" * 40)
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.database as database

# Rebind engine/session to a shared in-memory SQLite before creating tables.
engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
database.engine = engine
database.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

from pydantic import ValidationError

from app.api.routes.matches import create_match
from app.core.database import Base
from app.models.category import Category
from app.models.item import Item
from app.models.match import Match  # noqa: F401 - registra la tabla en Base
from app.models.message import Message
from app.models.user import User, UserRole
from app.schemas.match import MatchCreate

Base.metadata.create_all(bind=engine)

db = database.SessionLocal()
owner = User(name="Owner", email="owner@utem.cl", password_hash="x", role=UserRole.STUDENT)
requester = User(name="Requester", email="req@utem.cl", password_hash="x", role=UserRole.STUDENT)
category = Category(name="Libros")
db.add_all([owner, requester, category])
db.commit()
item = Item(
    title="Libro de Calculo",
    description="Descripcion suficientemente larga",
    condition="Usado",
    category_id=category.id,
    owner_id=owner.id,
)
db.add(item)
db.commit()

# 1) El schema rechaza una solicitud sin mensaje (422 en HTTP).
try:
    MatchCreate(item_id=item.id)
    raise SystemExit("FAIL: MatchCreate acepto una solicitud sin mensaje")
except ValidationError:
    pass

# 2) create_match crea el match Y su primer mensaje en la misma operacion.
match = create_match(MatchCreate(item_id=item.id, message="Hola, me interesa"), db, requester)
messages = db.query(Message).filter(Message.match_id == match.id).all()
assert len(messages) == 1, f"FAIL: se esperaba 1 mensaje, hay {len(messages)}"
assert messages[0].sender_id == requester.id, "FAIL: el mensaje no es del solicitante"
assert messages[0].content == "Hola, me interesa", "FAIL: contenido del mensaje incorrecto"

print("OK: la solicitud exige mensaje y crea match + primer mensaje")
