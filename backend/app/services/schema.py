from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def ensure_runtime_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    item_columns = {column["name"] for column in inspector.get_columns("items")}

    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            # Postgres no soporta CREATE TYPE IF NOT EXISTS; el DO/EXCEPTION lo
            # hace idempotente. Normalmente create_all ya creo estos enums, pero
            # una BD vieja sin la columna tampoco tendra el tipo.
            connection.execute(text(
                "DO $$ BEGIN CREATE TYPE userrole AS ENUM ('STUDENT', 'ADMIN'); "
                "EXCEPTION WHEN duplicate_object THEN null; END $$"
            ))
            connection.execute(text(
                "DO $$ BEGIN CREATE TYPE itemmoderationstatus AS ENUM ('PENDING', 'APPROVED', 'HIDDEN'); "
                "EXCEPTION WHEN duplicate_object THEN null; END $$"
            ))
            if "role" not in user_columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN role userrole NOT NULL DEFAULT 'STUDENT'")
                )
            if "moderation_status" not in item_columns:
                connection.execute(
                    text("ALTER TABLE items ADD COLUMN moderation_status itemmoderationstatus NOT NULL DEFAULT 'APPROVED'")
                )
            if "is_reported" not in item_columns:
                connection.execute(
                    text("ALTER TABLE items ADD COLUMN is_reported BOOLEAN NOT NULL DEFAULT FALSE")
                )
            # base64 data URLs exceed VARCHAR(500). TEXT has no length cap.
            # varchar->text is metadata-only in Postgres and idempotent.
            connection.execute(text("ALTER TABLE item_images ALTER COLUMN image_url TYPE TEXT"))
            return

        if "role" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(7) NOT NULL DEFAULT 'STUDENT'"))
        if "moderation_status" not in item_columns:
            connection.execute(text("ALTER TABLE items ADD COLUMN moderation_status VARCHAR(8) NOT NULL DEFAULT 'APPROVED'"))
        if "is_reported" not in item_columns:
            connection.execute(text("ALTER TABLE items ADD COLUMN is_reported BOOLEAN NOT NULL DEFAULT 0"))