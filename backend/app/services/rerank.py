"""Reranking: un cross-encoder reordena los candidatos que trajo la fusion.

El ranker vectorial compara dos embeddings calculados por separado. El
cross-encoder lee la pregunta y el fragmento juntos, en la misma pasada: acierta
mas, pero es demasiado lento para todo el repo. Por eso va segundo, sobre las
decenas de candidatos del pool hibrido.

    docker compose exec backend python -m app.services.rerank
"""
from functools import lru_cache

from sentence_transformers import CrossEncoder

from app.core.config import settings
from app.models.chunk import CodeChunk


# repoqa: cada par (pregunta, fragmento) se trunca a 512 tokens, asi que un
# fragmento largo se evalua por su comienzo. Si la evaluacion muestra que eso
# cuesta aciertos, el arreglo es partir los fragmentos largos al indexar.
MAX_TOKENS = 512


@lru_cache(maxsize=1)
def get_model() -> CrossEncoder:
    """Carga perezosa: importar la app o usar otro modo no debe costar la descarga."""
    return CrossEncoder(settings.rerank_model, max_length=MAX_TOKENS)


def rerank(question: str, chunks: list[CodeChunk]) -> list[tuple[CodeChunk, float]]:
    """Todos los fragmentos, del mas al menos relevante para la pregunta.

    El modelo ve la ruta ademas del contenido: `models/user.py` es senal cuando
    la pregunta es "donde se define...".

    Si el modelo no carga o falla, la excepcion sube tal cual. No hay vuelta
    silenciosa al orden original: esconderia que configuracion se esta sirviendo.
    """
    if not chunks:
        return []
    pairs = [(question, f"{chunk.file_path}\n{chunk.content}") for chunk in chunks]
    scores = get_model().predict(pairs, batch_size=16, show_progress_bar=False)
    return sorted(zip(chunks, (float(score) for score in scores)), key=lambda pair: -pair[1])


def _self_check() -> None:
    # Sin candidatos no hay nada que puntuar, y no se carga el modelo.
    assert rerank("cualquier cosa", []) == []

    relevant = CodeChunk(
        file_path="backend/app/core/security.py",
        content=(
            "def hash_password(password: str) -> str:\n"
            "    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()"
        ),
    )
    unrelated = CodeChunk(
        file_path="frontend/src/styles.css",
        content=".navbar {\n  display: flex;\n  gap: 12px;\n}",
    )
    # El relevante entra segundo a proposito: si sale primero es porque el
    # modelo lo puntuo mas alto, no porque se conservo el orden de entrada.
    ranked = rerank("que algoritmo se usa para hashear las contrasenas", [unrelated, relevant])

    assert [chunk for chunk, _ in ranked] == [relevant, unrelated], ranked
    # Mayor = mejor. Si esto cae, el orden esta invertido.
    assert ranked[0][1] > ranked[1][1], ranked

    print(f"rerank OK — {settings.rerank_model}")


if __name__ == "__main__":
    _self_check()
