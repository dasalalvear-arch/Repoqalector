"""Embeddings locales con sentence-transformers. Sin API key y sin costo por uso.

El modelo pesa ~90MB y se descarga la primera vez que se usa (queda cacheado en
HF_HOME, que docker-compose monta como volumen). La primera llamada despues de
levantar el contenedor tarda unos segundos; las siguientes son inmediatas.
"""
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.models.chunk import EMBEDDING_DIM

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """Carga perezosa: el import de la app no deberia costar 90MB de descarga."""
    model = SentenceTransformer(MODEL_NAME)
    loaded_dim = model.get_sentence_embedding_dimension()
    if loaded_dim != EMBEDDING_DIM:
        # Fallar aqui y no al insertar: un mismatch de dimension significa que
        # los vectores guardados y los nuevos no son comparables.
        raise RuntimeError(
            f"{MODEL_NAME} devuelve {loaded_dim} dimensiones pero la tabla espera "
            f"{EMBEDDING_DIM}. Cambiar de modelo obliga a reindexar todo."
        )
    return model


def embed(texts: list[str]) -> list[list[float]]:
    """Embeddings de un lote de textos, en el mismo orden que la entrada."""
    if not texts:
        return []
    vectors = get_model().encode(texts, batch_size=32, show_progress_bar=False)
    return [vector.tolist() for vector in vectors]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]
