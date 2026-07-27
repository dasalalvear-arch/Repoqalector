"""Mide la calidad de la recuperacion contra un set de preguntas con respuesta conocida.

Mide *solo* la recuperacion, no la generacion: si el archivo correcto no entra
en el top-k, ningun LLM va a responder bien. Sin este numero no hay forma de
saber si un cambio de modelo o de troceo mejora o empeora las cosas.

Llama a `retrieval.search()`, el mismo camino que usa la API. Una implementacion
paralela seria mas comoda para comparar modelos sin reindexar, pero puede
divergir en silencio — y si diverge, el numero medido no es el que el usuario
experimenta. Comparar modelos vuelve a costar un reindexado (~16s).

El set vive en `backend/eval/*.json`, no en el codigo: cambiar de repo de prueba
es cambiar de archivo, no de programa.

    docker compose exec backend python -m app.services.evaluate eval/uswap.json
    docker compose exec backend python -m app.services.evaluate eval/uswap.json vector
"""
import json
import sys
from pathlib import Path

from app.core.database import SessionLocal
from app.services import retrieval

TOP_K = 5


def load_set(path: Path) -> tuple[str, list[tuple[str, list[str]]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = [(item["question"], item["expect"]) for item in data["questions"]]
    return data["repo"], questions


def evaluate(eval_path: Path, mode: str = "hybrid") -> float:
    repo, questions = load_set(eval_path)

    db = SessionLocal()
    try:
        if not retrieval.repo_exists(db, repo):
            sys.exit(f"No hay chunks indexados para {repo}. Corre POST /repos primero.")

        print(f"\nRepo:  {repo}")
        print(f"Modo:  {mode} | Preguntas: {len(questions)} | top_k={TOP_K}\n")

        hits_at_1 = hits_at_k = 0
        for question, expected in questions:
            hits = retrieval.search(db, repo, question, TOP_K, mode)
            paths = [hit.file_path for hit in hits]
            rank = next(
                (i + 1 for i, path in enumerate(paths) if any(e in path for e in expected)),
                None,
            )

            hits_at_1 += rank == 1
            hits_at_k += rank is not None
            mark = "OK   " if rank == 1 else ("top5 " if rank else "FALLA")
            detail = f"rank {rank}" if rank else f"trajo {paths[0] if paths else '(nada)'}"
            print(f"  {mark} {question[:50]:<50} -> {expected[0]:<22} {detail}")
    finally:
        db.close()

    total = len(questions)
    print(f"\n  acierto@1:  {hits_at_1}/{total} ({100 * hits_at_1 // total}%)")
    print(f"  acierto@{TOP_K}:  {hits_at_k}/{total} ({100 * hits_at_k // total}%)\n")
    return hits_at_k / total


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    evaluate(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "hybrid")
