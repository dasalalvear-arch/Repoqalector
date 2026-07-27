"""Demo data seeder: 2 student users + 7 published items for manual testing.

Idempotent — users are matched by email and items by title, so anything that
already exists is left untouched and re-running never duplicates.

Run against a running stack (Docker):
    docker compose exec backend python -m app.services.seed_demo

Or locally (backend venv active, DB reachable):
    python -m app.services.seed_demo

Both demo students log in with the password "demo1234".
"""
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.category import Category
from app.models.item import Item
from app.models.user import User, UserRole

DEMO_PASSWORD = "demo1234"

DEMO_USERS = [
    {"name": "Valentina Rojas", "email": "valentina.rojas@utem.cl", "career": "Ingenieria en Informatica"},
    {"name": "Matias Fuentes", "email": "matias.fuentes@utem.cl", "career": "Ingenieria Civil"},
]

# (title, description, condition, category_name, owner_index)
DEMO_ITEMS = [
    ("Calculadora Casio fx-991EX", "Cientifica, todas las funciones operativas. Ideal para Calculo y Algebra.", "Buen estado", "Tecnologia", 0),
    ("Cargador USB-C 65W", "Carga rapida para notebook, incluye cable.", "Como nuevo", "Tecnologia", 1),
    ("Arduino Uno R3 + set de cables", "Usado en un solo ramo, funciona perfecto para proyectos.", "Usado", "Tecnologia", 0),
    ("Set de plumones de pizarra", "Cuatro colores, casi sin uso.", "Nuevo", "Papeleria", 1),
    ("Block de croquis A3", "Quedan unas 30 hojas, util para dibujo tecnico.", "Sin uso", "Papeleria", 0),
    ("Calculo de una variable - Stewart", "8va edicion, algunas notas a lapiz.", "Buen estado", "Bibliografia", 1),
    ("Fisica Universitaria - Sears Zemansky", "Tomo 1, subrayado pero completo.", "Usado", "Bibliografia", 0),
]


def seed_demo() -> None:
    db = SessionLocal()
    try:
        # Ensure the demo students exist (matched by email).
        users: list[User] = []
        for data in DEMO_USERS:
            user = db.query(User).filter(User.email == data["email"]).first()
            if user is None:
                user = User(
                    name=data["name"],
                    email=data["email"],
                    career=data["career"],
                    password_hash=hash_password(DEMO_PASSWORD),
                    role=UserRole.STUDENT,
                )
                db.add(user)
                db.flush()  # assign user.id for the items below
            users.append(user)

        # Categories are seeded at startup; create any missing one just in case.
        categories = {category.name: category for category in db.query(Category).all()}

        created = 0
        for title, description, condition, category_name, owner_index in DEMO_ITEMS:
            if db.query(Item).filter(Item.title == title).first() is not None:
                continue  # already seeded
            category = categories.get(category_name)
            if category is None:
                category = Category(name=category_name)
                db.add(category)
                db.flush()
                categories[category_name] = category
            db.add(
                Item(
                    title=title,
                    description=description,
                    condition=condition,
                    category_id=category.id,
                    owner_id=users[owner_index].id,
                )
            )
            created += 1

        db.commit()
        print(f"Demo seed listo: {len(users)} usuarios asegurados, {created} items nuevos agregados.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo()
