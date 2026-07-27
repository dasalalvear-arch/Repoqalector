from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.category import Category
from app.models.user import User, UserRole

DEFAULT_CATEGORIES = ["Tecnologia", "Papeleria", "Bibliografia"]


def create_admin() -> None:
    """Crea el usuario administrador desde las credenciales del .env si aun
    no existe. No hace nada si ADMIN_EMAIL/ADMIN_PASSWORD no estan definidos."""
    if not settings.admin_email or not settings.admin_password:
        return

    email = settings.admin_email.lower()
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first() is not None:
            return
        db.add(
            User(
                name=settings.admin_name,
                email=email,
                password_hash=hash_password(settings.admin_password),
                role=UserRole.ADMIN,
            )
        )
        db.commit()
    finally:
        db.close()


def ensure_default_categories(db: Session) -> None:
    existing = {category.name for category in db.query(Category).all()}
    for name in DEFAULT_CATEGORIES:
        if name not in existing:
            db.add(Category(name=name))
    db.commit()
