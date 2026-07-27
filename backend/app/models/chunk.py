from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# all-MiniLM-L6-v2 produce 384 dimensiones. Si cambias de modelo de embeddings
# este numero cambia y hay que reindexar: los vectores viejos no son comparables.
EMBEDDING_DIM = 384

# Configuracion de texto de Postgres. Elimina las palabras vacias del espanol
# (que en una pregunta son casi todo) y deja intactos los identificadores:
#   'donde se valida que el correo sea @utem.cl' -> 'val' & 'corre' & 'utem.cl'
TEXT_SEARCH_CONFIG = "spanish"


class CodeChunk(Base):
    """Un fragmento de codigo indexado, con su embedding y su procedencia exacta.

    file_path + line_start/line_end son lo que se le muestra al usuario como
    cita; sin ellos la respuesta del LLM no es verificable.
    """

    __tablename__ = "code_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    line_start: Mapped[int] = mapped_column(nullable=False)
    line_end: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    # Columna generada: la mantiene Postgres en cada INSERT/UPDATE, asi que no
    # puede desincronizarse de `content` y la ingesta no necesita saber que existe.
    # Incluye file_path porque el nombre del archivo es senal fuerte: una pregunta
    # sobre autenticacion deberia favorecer routes/auth.py aunque el cuerpo del
    # fragmento no repita la palabra.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            f"to_tsvector('{TEXT_SEARCH_CONFIG}', file_path || ' ' || content)",
            persisted=True,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# repoqa: sin indice ANN (ivfflat/hnsw) sobre embedding — con un repo mediano el
# scan secuencial responde en milisegundos. Agregar hnsw si se nota lento.
Index("ix_code_chunks_repo_file", CodeChunk.repo, CodeChunk.file_path)
# GIN es lo que hace instantanea la busqueda lexica.
Index("ix_code_chunks_search", CodeChunk.search_vector, postgresql_using="gin")
