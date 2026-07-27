"""Mide la calidad de la recuperacion contra un set de preguntas con respuesta conocida.

Mide *solo* la recuperacion, no la generacion: si el archivo correcto no entra
en el top-k, ningun LLM va a responder bien. Sin este numero no hay forma de
saber si un cambio de modelo o de troceo mejora o empeora las cosas.

El set vive en `backend/eval/*.json`, no en el codigo: cambiar de repo de
prueba es cambiar de archivo, no de programa.

    docker compose exec backend python -m app.services.evaluate eval/uswap.json

Con un segundo argumento evalua ese modelo en vez del configurado, re-embediendo
en memoria sin tocar la BD — sirve para comparar antes de decidir un reindexado:

    docker compose exec backend python -m app.services.evaluate eval/uswap.json \\
        sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
"""
import json
import sys
from pathlib import Path

import numpy as np

from app.core.database import SessionLocal
from app.models.chunk import CodeChunk

TOP_K = 5


def load_set(path: Path) -> tuple[str, list[tuple[str, str]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = [(q["question"], q["expect"]) for q in data["questions"]]
    return data["repo"], questions


def normalize(matrix: np.ndarray) -> np.ndarray:
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def evaluate(eval_path: Path, model_name: str | None = None) -> float:
    repo, questions = load_set(eval_path)

    db = SessionLocal()
    try:
        chunks = db.query(CodeChunk).filter(CodeChunk.repo == repo).all()
    finally:
        db.close()
    if not chunks:
        sys.exit(f"No hay chunks indexados para {repo}. Corre POST /repos primero.")

    if model_name:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name)
        matrix = np.array(model.encode([c.content for c in chunks], batch_size=32))
        question_vectors = np.array(model.encode([q for q, _ in questions]))
    else:
        from app.services.embeddings import MODEL_NAME, embed

        model_name = MODEL_NAME
        matrix = np.array([c.embedding for c in chunks])
        question_vectors = np.array(embed([q for q, _ in questions]))

    # Coseno sobre vectores normalizados = producto punto.
    matrix = normalize(matrix)
    question_vectors = normalize(question_vectors)

    print(f"\nRepo:    {repo}")
    print(f"Modelo:  {model_name}")
    print(f"Chunks:  {len(chunks)} | Preguntas: {len(questions)} | top_k={TOP_K}\n")

    hits_at_1 = hits_at_k = 0
    for (question, expected), vector in zip(questions, question_vectors):
        ranked = np.argsort(-(matrix @ vector))[:TOP_K]
        paths = [chunks[i].file_path for i in ranked]
        rank = next((i + 1 for i, path in enumerate(paths) if expected in path), None)

        hits_at_1 += rank == 1
        hits_at_k += rank is not None
        mark = "OK   " if rank == 1 else ("top5 " if rank else "FALLA")
        detail = f"rank {rank}" if rank else f"trajo {paths[0]}"
        print(f"  {mark} {question[:50]:<50} -> {expected:<22} {detail}")

    total = len(questions)
    print(f"\n  acierto@1:  {hits_at_1}/{total} ({100 * hits_at_1 // total}%)")
    print(f"  acierto@{TOP_K}:  {hits_at_k}/{total} ({100 * hits_at_k // total}%)\n")
    return hits_at_1 / total


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    evaluate(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else None)
