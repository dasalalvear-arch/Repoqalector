# Hybrid Retrieval (Phase A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise retrieval from 13% to ≥80% hit@5 by fusing pgvector similarity search with Postgres full-text search, without adding any external API call or paid dependency.

**Architecture:** A generated `tsvector` column on `code_chunks` gives Postgres a lexical index alongside the existing embedding column. A new `services/retrieval.py` runs both rankers, fuses their *positions* with Reciprocal Rank Fusion, and down-weights documentation files. The `/search` route becomes a thin HTTP wrapper, and the eval harness calls the same service function so the measurement reflects the real code path.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, PostgreSQL 16 + pgvector, sentence-transformers (local, `all-MiniLM-L6-v2`), React + TypeScript + Vite.

**Spec:** `docs/superpowers/specs/2026-07-27-hybrid-retrieval-design.md`

## Global Constraints

- **No test framework.** This repo has no pytest and no linter. The established convention is a `_self_check()` function guarded by `if __name__ == "__main__":`, using plain `assert`, run with `python -m app.services.<module>`. Follow it. Do not add pytest.
- **The only automated gate is `cd frontend && npm run build`** (`tsc -b && vite build`). Run it before committing any frontend change.
- **Identifiers in English; code comments and user-visible strings in Spanish.** Existing files follow this — match them.
- **No migrations.** `create_all` does not alter existing tables. Schema changes require `docker compose down -v` followed by a reindex.
- **Local-only repo, no remote.** Never add a git remote, never push.
- **Mark deliberate shortcuts with a `repoqa:` comment** naming the ceiling and the upgrade path.
- **Constants from the spec, exact values:** `CANDIDATES_PER_RANKER = 30`, `RRF_K = 60`, `DOC_WEIGHT = 0.7`, `DOC_EXTENSIONS = {".md", ".rst"}`.
- **Postgres text search configuration is `'spanish'`** everywhere — both the indexed vector and the query.
- Docker must be running. If `docker compose` reports it cannot reach the daemon, start Docker Desktop before continuing.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/models/chunk.py` | **Modify.** Add the generated `search_vector` column and its GIN index. |
| `backend/app/services/retrieval.py` | **Create.** All retrieval logic: query building, both rankers, RRF fusion, and the three modes. Holds the self-checks for its pure functions. |
| `backend/app/schemas/repo.py` | **Modify.** `SearchHit.distance` → `score`; add `mode` to `SearchRequest`. |
| `backend/app/api/routes/search.py` | **Modify.** Shrink to an HTTP wrapper: validate, call the service, translate an unknown repo to 404. |
| `backend/app/services/evaluate.py` | **Modify.** Drop the parallel numpy ranking; call `retrieval.search()`; accept multi-valued `expect`; report per-mode. |
| `backend/eval/uswap.json` | **Modify.** `expect` becomes a list of acceptable paths. |
| `frontend/src/services/api.ts` | **Modify.** `SearchHit.distance` → `score`. |
| `frontend/src/pages/AskPage.tsx` | **Modify.** Render `score` instead of `dist`. |

Retrieval lives in one module because query building, ranking, and fusion always change together — splitting them across files by technical layer would spread a single decision over three places.

---

### Task 1: Lexical index column

**Files:**
- Modify: `backend/app/models/chunk.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `CodeChunk.search_vector` — a `TSVECTOR` column, maintained by Postgres, containing `to_tsvector('spanish', file_path || ' ' || content)`. Task 3 queries it with `@@` and `ts_rank_cd`.

- [ ] **Step 1: Add the column and index**

Replace the entire contents of `backend/app/models/chunk.py` with:

```python
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
```

- [ ] **Step 2: Recreate the database and reindex**

The column cannot be added to the existing table — there are no migrations.

```bash
docker compose down -v
```

```bash
docker compose up -d --build backend
```

Wait ~10 seconds for startup, then reindex the test repo:

```bash
curl -X POST http://localhost:8000/repos -H "Content-Type: application/json" -d "{\"url\":\"https://github.com/dasalalvear-arch/u-swap\"}"
```

Expected: `{"repo":"dasalalvear-arch/u-swap","chunks":150,"files":57}`

- [ ] **Step 3: Verify the column is populated and the lexical index works**

```bash
docker compose exec -T db psql -U repoqa -d repoqa -c "SELECT file_path, line_start FROM code_chunks WHERE search_vector @@ plainto_tsquery('spanish', 'utem.cl') AND file_path LIKE '%auth%';"
```

Expected: at least one row for `backend/app/api/routes/auth.py`. This is the concrete proof the lexical half can find what the vector half missed — if this returns zero rows, stop and investigate before continuing.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/chunk.py
git commit -m "feat: add generated tsvector column for lexical search"
```

---

### Task 2: Pure retrieval functions

**Files:**
- Create: `backend/app/services/retrieval.py`

**Interfaces:**
- Consumes: `CodeChunk` from Task 1 (imported, not yet queried).
- Produces:
  - `build_tsquery(question: str) -> str` — returns OR-joined lexemes, or `""` when the question has no usable term.
  - `fuse(ranked_ids: list[list[int]], paths: dict[int, str]) -> list[tuple[int, float]]` — returns `(chunk_id, score)` sorted by descending score.
  - Constants `CANDIDATES_PER_RANKER`, `RRF_K`, `DOC_WEIGHT`.

Task 3 adds `search()` to this same file.

- [ ] **Step 1: Write the failing self-check**

Create `backend/app/services/retrieval.py` with only the checks and empty stubs, so the check fails for the right reason:

```python
"""Recuperacion: busqueda vectorial, busqueda lexica y su fusion."""
import re

CANDIDATES_PER_RANKER = 30
RRF_K = 60
DOC_WEIGHT = 0.7
DOC_EXTENSIONS = (".md", ".rst")


def build_tsquery(question: str) -> str:
    raise NotImplementedError


def fuse(ranked_ids: list[list[int]], paths: dict[int, str]) -> list[tuple[int, float]]:
    raise NotImplementedError


def _self_check() -> None:
    # --- build_tsquery ---------------------------------------------------
    # Los identificadores con punto sobreviven enteros: son el ancla exacta
    # que la busqueda vectorial no encuentra.
    assert build_tsquery("donde se valida el correo @utem.cl") == (
        "donde | se | valida | el | correo | utem.cl"
    ), build_tsquery("donde se valida el correo @utem.cl")

    # OR, no AND: exigir todos los terminos fue el error de la medicion previa.
    assert "&" not in build_tsquery("hash de contrasenas")

    # Una pregunta sin terminos utilizables no puede reventar: la mitad lexica
    # queda vacia y la fusion degrada a solo-vectorial.
    assert build_tsquery("...") == "", build_tsquery("...")
    assert build_tsquery("  ") == ""

    # --- fuse -------------------------------------------------------------
    code = {1: "a.py", 2: "b.py", 3: "c.py", 4: "d.py", 5: "e.py"}

    # Estar en ambas listas gana sobre dominar una sola.
    fused = fuse([[1, 2, 3], [2, 4, 5]], code)
    assert fused[0][0] == 2, fused

    # Un documento presente en una sola lista igual sobrevive.
    assert 4 in [chunk_id for chunk_id, _ in fused], fused
    assert len(fused) == 5, fused

    # Una lista vacia no rompe la fusion.
    only_one = fuse([[], [7]], {7: "x.py"})
    assert only_one == [(7, 1.0 / (RRF_K + 1))], only_one

    # DOC_WEIGHT hunde un .md que iba por delante de un archivo de codigo.
    mixed = fuse([[10, 20]], {10: "README.md", 20: "app.py"})
    assert mixed[0][0] == 20, mixed

    # Sin la penalizacion, el .md iba primero: confirma que el orden cambio por
    # DOC_WEIGHT y no porque el ranking ya lo pusiera segundo.
    unpenalized = fuse([[10, 20]], {10: "a.py", 20: "app.py"})
    assert unpenalized[0][0] == 10, unpenalized

    print("retrieval OK — tsquery y fusion RRF")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
docker compose exec -T backend python -m app.services.retrieval
```

Expected: `NotImplementedError` raised from `build_tsquery`.

- [ ] **Step 3: Implement the two functions**

Replace the two stubs with:

```python
def build_tsquery(question: str) -> str:
    """Convierte la pregunta en una tsquery con OR entre terminos.

    El patron `[\\w.]+` cumple doble funcion: preserva identificadores como
    `utem.cl` y descarta por construccion los caracteres con significado
    sintactico en tsquery (`&`, `|`, `!`, `:`, parentesis). Los puntos sueltos
    se recortan para que "..." no genere un termino vacio.

    Devuelve "" cuando no queda ningun termino; quien llame debe tratarlo como
    "no hay busqueda lexica", no como error.
    """
    terms = [token.strip(".") for token in re.findall(r"[\w.]+", question.lower())]
    return " | ".join(term for term in terms if term)


def _is_doc(path: str) -> bool:
    return path.lower().endswith(DOC_EXTENSIONS)


def fuse(ranked_ids: list[list[int]], paths: dict[int, str]) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion sobre varias listas ordenadas por relevancia.

    Cada documento suma 1/(RRF_K + posicion) por cada lista donde aparece. Se
    usan las *posiciones* y no los puntajes porque la distancia coseno (0 a 2) y
    ts_rank_cd (sin cota superior) viven en escalas incomparables: normalizarlas
    exigiria calibrar, los rankings no.

    DOC_WEIGHT se aplica antes de que el llamador recorte a top_k — penalizar
    una lista ya truncada no cambiaria que documentos sobreviven.
    """
    scores: dict[int, float] = {}
    for ranked in ranked_ids:
        for position, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + position)

    for chunk_id in scores:
        if _is_doc(paths[chunk_id]):
            scores[chunk_id] *= DOC_WEIGHT

    return sorted(scores.items(), key=lambda pair: -pair[1])
```

- [ ] **Step 4: Run it to verify it passes**

```bash
docker compose exec -T backend python -m app.services.retrieval
```

Expected: `retrieval OK — tsquery y fusion RRF`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/retrieval.py
git commit -m "feat: RRF fusion and tsquery builder with self-check"
```

---

### Task 3: The search service and the API contract

**Files:**
- Modify: `backend/app/services/retrieval.py` (append)
- Modify: `backend/app/schemas/repo.py`
- Modify: `backend/app/api/routes/search.py`

**Interfaces:**
- Consumes: `build_tsquery`, `fuse`, `CANDIDATES_PER_RANKER` (Task 2); `CodeChunk.search_vector` (Task 1); `embed_one` from `app.services.embeddings`.
- Produces:
  - `search(db: Session, repo: str, question: str, top_k: int = 5, mode: str = "hybrid") -> list[SearchHit]`
  - `repo_exists(db: Session, repo: str) -> bool`
  - `SearchHit` with field `score: float` (higher is better), replacing `distance`.
  - `SearchRequest` with field `mode: Literal["vector", "lexical", "hybrid"]`, default `"hybrid"`.

Task 4 calls `search()` with each of the three modes. Task 5 renders `score`.

- [ ] **Step 1: Update the schemas**

Replace the contents of `backend/app/schemas/repo.py` with:

```python
from typing import Literal

from pydantic import BaseModel, Field

SearchMode = Literal["vector", "lexical", "hybrid"]


class IndexRepoRequest(BaseModel):
    url: str = Field(description="URL https de un repositorio publico de GitHub")


class IndexRepoResponse(BaseModel):
    repo: str
    chunks: int
    files: int


class RepoSummary(BaseModel):
    repo: str
    chunks: int


class SearchRequest(BaseModel):
    repo: str
    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    mode: SearchMode = "hybrid"


class SearchHit(BaseModel):
    file_path: str
    line_start: int
    line_end: int
    content: str
    # Mayor es mejor, en los tres modos. No es una distancia: el puntaje de RRF
    # no tiene unidad, y en modo vectorial se reporta 1 - distancia_coseno para
    # que la direccion sea la misma y las comparaciones no se inviertan.
    score: float
```

- [ ] **Step 2: Append the service to `retrieval.py`**

Add these imports at the top of `backend/app/services/retrieval.py`, after `import re`:

```python
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chunk import TEXT_SEARCH_CONFIG, CodeChunk
from app.schemas.repo import SearchHit
from app.services.embeddings import embed_one
```

Then append, **above** `def _self_check()`:

```python
def repo_exists(db: Session, repo: str) -> bool:
    return db.query(CodeChunk.id).filter(CodeChunk.repo == repo).first() is not None


def _vector_candidates(db: Session, repo: str, question: str) -> list[tuple[CodeChunk, float]]:
    """Candidatos por similitud de embeddings. Devuelve (chunk, score) con mayor = mejor."""
    distance = CodeChunk.embedding.cosine_distance(embed_one(question))
    rows = db.execute(
        select(CodeChunk, distance.label("distance"))
        .filter(CodeChunk.repo == repo)
        .order_by(distance)
        .limit(CANDIDATES_PER_RANKER)
    ).all()
    return [(chunk, 1.0 - float(value)) for chunk, value in rows]


def _lexical_candidates(db: Session, repo: str, question: str) -> list[tuple[CodeChunk, float]]:
    """Candidatos por texto completo. Lista vacia si la pregunta no deja terminos."""
    terms = build_tsquery(question)
    if not terms:
        return []

    tsquery = func.to_tsquery(TEXT_SEARCH_CONFIG, terms)
    rank = func.ts_rank_cd(CodeChunk.search_vector, tsquery)
    rows = db.execute(
        select(CodeChunk, rank.label("rank"))
        .filter(CodeChunk.repo == repo, CodeChunk.search_vector.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(CANDIDATES_PER_RANKER)
    ).all()
    return [(chunk, float(value)) for chunk, value in rows]


def _to_hits(scored: list[tuple[CodeChunk, float]], top_k: int) -> list[SearchHit]:
    return [
        SearchHit(
            file_path=chunk.file_path,
            line_start=chunk.line_start,
            line_end=chunk.line_end,
            content=chunk.content,
            score=round(score, 4),
        )
        for chunk, score in scored[:top_k]
    ]


def search(
    db: Session,
    repo: str,
    question: str,
    top_k: int = 5,
    mode: str = "hybrid",
) -> list[SearchHit]:
    """Busqueda semantica, lexica o fusionada sobre un repo indexado.

    `mode` existe para poder medir cada mitad por separado en la evaluacion. La
    ruta HTTP usa "hybrid"; los otros dos modos son instrumentos de medicion.
    """
    if mode == "vector":
        return _to_hits(_vector_candidates(db, repo, question), top_k)
    if mode == "lexical":
        return _to_hits(_lexical_candidates(db, repo, question), top_k)

    vector = _vector_candidates(db, repo, question)
    lexical = _lexical_candidates(db, repo, question)

    by_id = {chunk.id: chunk for chunk, _ in vector + lexical}
    paths = {chunk_id: chunk.file_path for chunk_id, chunk in by_id.items()}
    ranked_ids = [
        [chunk.id for chunk, _ in vector],
        [chunk.id for chunk, _ in lexical],
    ]
    fused = fuse(ranked_ids, paths)
    return _to_hits([(by_id[chunk_id], score) for chunk_id, score in fused], top_k)
```

- [ ] **Step 3: Shrink the route to a wrapper**

Replace the contents of `backend/app/api/routes/search.py` with:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.repo import SearchHit, SearchRequest
from app.services import retrieval

router = APIRouter()


@router.post("", response_model=list[SearchHit])
def search(payload: SearchRequest, db: Session = Depends(get_db)) -> list[SearchHit]:
    """Busqueda semantica pura, sin LLM.

    Existe para poder evaluar la recuperacion por separado de la generacion: si
    los chunks que salen de aqui no contienen la respuesta, ningun modelo la va
    a inventar bien. Es el paso previo a /ask.
    """
    # Un repo mal escrito devolvia lista vacia, indistinguible de "no encontre
    # nada". El 404 lo dice.
    if not retrieval.repo_exists(db, payload.repo):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El repositorio '{payload.repo}' no esta indexado",
        )
    return retrieval.search(db, payload.repo, payload.question, payload.top_k, payload.mode)
```

- [ ] **Step 4: Verify the self-check still passes and the endpoint works**

```bash
docker compose restart backend
```

Wait ~8 seconds, then:

```bash
docker compose exec -T backend python -m app.services.retrieval
```

Expected: `retrieval OK — tsquery y fusion RRF`

The question that failed hardest before — it should now surface `auth.py`:

```bash
curl -s -X POST http://localhost:8000/search -H "Content-Type: application/json" -d "{\"repo\":\"dasalalvear-arch/u-swap\",\"question\":\"donde se valida que el correo sea @utem.cl\",\"top_k\":3}"
```

Expected: JSON array where at least one hit has `file_path` containing `routes/auth.py`, and every hit has a `score` field (no `distance`).

An unknown repo must 404:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/search -H "Content-Type: application/json" -d "{\"repo\":\"no/existe\",\"question\":\"hola\"}"
```

Expected: `404`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/retrieval.py backend/app/schemas/repo.py backend/app/api/routes/search.py
git commit -m "feat: hybrid search service, score replaces distance, 404 on unknown repo"
```

---

### Task 4: Eval harness measures the real path

**Files:**
- Modify: `backend/eval/uswap.json`
- Modify: `backend/app/services/evaluate.py`

**Interfaces:**
- Consumes: `retrieval.search()` and `SearchHit.score` (Task 3).
- Produces: `evaluate(eval_path: Path, mode: str) -> float` returning hit@5 as a fraction. Task 6 reads its printed output.

- [ ] **Step 1: Allow several valid files per question**

Replace the contents of `backend/eval/uswap.json` with:

```json
{
  "repo": "dasalalvear-arch/u-swap",
  "note": "Preguntas en espanol (el idioma de la interfaz) con la respuesta verificada a mano leyendo el repo. `expect` lista todas las rutas que cuentan como respuesta correcta: varias preguntas tienen mas de un origen legitimo.",
  "questions": [
    { "question": "donde se valida que el correo sea @utem.cl", "expect": ["routes/auth.py"] },
    { "question": "que algoritmo se usa para hashear las contrasenas", "expect": ["core/security.py"] },
    { "question": "como se genera el token JWT de acceso", "expect": ["core/security.py"] },
    { "question": "donde se define la tabla de usuarios", "expect": ["models/user.py"] },
    { "question": "como se crea el usuario administrador al arrancar", "expect": ["services/seed.py", "core/config.py"] },
    { "question": "que endpoint devuelve las metricas del panel de admin", "expect": ["routes/admin.py"] },
    { "question": "como se filtra el catalogo por categoria", "expect": ["routes/items.py", "pages/CatalogPage.tsx"] },
    { "question": "donde se guardan las imagenes de una publicacion", "expect": ["models/item.py", "schemas/item.py"] },
    { "question": "como se envia un mensaje en el chat", "expect": ["routes/chat.py", "pages/MatchesPage.tsx"] },
    { "question": "que estados puede tener una solicitud de intercambio", "expect": ["models/match.py", "schemas/match.py"] },
    { "question": "como se limita la cantidad de intentos de login", "expect": ["core/limiter.py", "routes/auth.py"] },
    { "question": "donde se configura la conexion a la base de datos", "expect": ["core/database.py", "core/config.py"] },
    { "question": "como sabe el frontend que el token expiro", "expect": ["services/api.ts", "hooks/useAuth.ts"] },
    { "question": "donde se decide si un usuario es admin", "expect": ["api/dependencies.py", "routes/admin.py"] },
    { "question": "que cabeceras de seguridad devuelve la api", "expect": ["app/main.py", "vite.config.ts"] }
  ]
}
```

- [ ] **Step 2: Rewrite the harness to call the real search**

Replace the contents of `backend/app/services/evaluate.py` with:

```python
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
```

- [ ] **Step 3: Verify it runs end to end**

```bash
docker compose exec -T backend python -m app.services.evaluate eval/uswap.json vector
```

Expected: 15 result lines and a summary. The `vector` mode is the old behaviour, so `acierto@5` should be close to the previously recorded 13% — a wildly different number means the harness changed what it measures, not just how.

- [ ] **Step 4: Commit**

```bash
git add backend/eval/uswap.json backend/app/services/evaluate.py
git commit -m "refactor: eval measures the real search path, accepts several valid files"
```

---

### Task 5: Frontend contract update

**Files:**
- Modify: `frontend/src/services/api.ts:8-14`
- Modify: `frontend/src/pages/AskPage.tsx:95`

**Interfaces:**
- Consumes: `SearchHit.score` from Task 3.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Rename the field in the shared type**

In `frontend/src/services/api.ts`, replace the `SearchHit` type:

```typescript
/** Un fragmento recuperado. `score`: mayor es mejor, en los tres modos. */
export type SearchHit = {
  file_path: string;
  line_start: number;
  line_end: number;
  content: string;
  score: number;
};
```

- [ ] **Step 2: Render it**

In `frontend/src/pages/AskPage.tsx`, replace this line:

```tsx
                        <span className="muted">dist {hit.distance}</span>
```

with:

```tsx
                        <span className="muted">score {hit.score}</span>
```

- [ ] **Step 3: Run the typecheck gate**

```bash
cd frontend && npm run build
```

Expected: `tsc -b` passes and Vite reports `✓ built in ...`. A `Property 'distance' does not exist` error means a usage was missed — fix it before committing.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/services/api.ts frontend/src/pages/AskPage.tsx
git commit -m "feat: frontend renders score instead of distance"
```

---

### Task 6: Measure and decide on phase B

**Files:**
- Modify: `README.md` (the Estado table and a new Resultados section)

**Interfaces:**
- Consumes: everything above.
- Produces: the recorded measurement that gates phase B.

- [ ] **Step 1: Measure all three modes**

```bash
docker compose exec -T backend python -m app.services.evaluate eval/uswap.json vector
```

```bash
docker compose exec -T backend python -m app.services.evaluate eval/uswap.json lexical
```

```bash
docker compose exec -T backend python -m app.services.evaluate eval/uswap.json hybrid
```

Record the `acierto@1` and `acierto@5` of each. Report the three numbers verbatim — do not round up, describe a miss as a hit, or claim the target was met if it was not.

- [ ] **Step 2: Tune `DOC_WEIGHT` only if it is the thing holding back the number**

Inspect the `hybrid` failures. If documentation files are still taking top-5 slots from code, lower `DOC_WEIGHT` in `backend/app/services/retrieval.py` to `0.5` and re-run the hybrid evaluation. Keep whichever value scores higher, and record both numbers.

If documentation is not appearing in the failures, leave `DOC_WEIGHT` at `0.7` — changing it would be tuning against noise.

- [ ] **Step 3: Record the results in the README**

In `README.md`, change the `POST /search` row of the Estado table to mention hybrid retrieval, and add this section directly after the Estado table, filling in the measured numbers:

```markdown
## Resultados de recuperación

Medido sobre `dasalalvear-arch/u-swap` (150 fragmentos, 57 archivos) con las 15
preguntas de `backend/eval/uswap.json`, cuya respuesta correcta se verificó a mano.

| Modo | acierto@1 | acierto@5 |
|---|---|---|
| Vectorial (embeddings) | X% | X% |
| Léxico (Postgres full-text) | X% | X% |
| **Híbrido (RRF)** | **X%** | **X%** |

La búsqueda vectorial sola falla porque un modelo de propósito general empareja mal
preguntas en lenguaje natural contra código crudo, y la documentación en prosa gana
el ranking por parecerse más a la pregunta. La mitad léxica aporta las anclas exactas
(`utem.cl`, `bcrypt`, `JWT`) que aparecen literalmente en el código.

Reproducir: `docker compose exec backend python -m app.services.evaluate eval/uswap.json <modo>`
```

- [ ] **Step 4: Commit**

```bash
git add README.md backend/app/services/retrieval.py
git commit -m "docs: record hybrid retrieval measurement"
```

- [ ] **Step 5: State the phase B decision**

Compare hybrid `acierto@5` against the 80% target from the spec and say plainly which happened:

- **≥80%:** phase A closes. The next work is `/ask`, which needs its own spec.
- **<80%:** phase A is the new baseline. Phase B (local cross-encoder reranking) is justified and needs its own plan. Report the exact gap.

Do not start phase B in this plan.

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Generated `tsvector` column, `'spanish'` config, includes `file_path` | 1 |
| GIN index | 1 |
| `down -v` + reindex consequence | 1, step 2 |
| `build_tsquery` with `[\w.]+`, OR-joined, parameterized | 2 |
| RRF fusion, `RRF_K = 60`, positions not scores | 2 |
| `DOC_WEIGHT = 0.7`, applied before `top_k` | 2 (fusion), 6 (calibration) |
| `CANDIDATES_PER_RANKER = 30` | 2 (constant), 3 (used) |
| `services/retrieval.py` with `search(db, repo, question, top_k, mode)` | 3 |
| Reuses `SearchHit`, no parallel type | 3 |
| Route as thin wrapper; 404 lives in the route | 3 |
| `distance` → `score`, higher is better; `1 - distance` in vector mode | 3 |
| Frontend updated in the same change | 5 |
| `expect` becomes a list | 4 |
| Eval calls the real path; numpy implementation dropped | 4 |
| Per-mode measurement | 4 (capability), 6 (execution) |
| Empty tsquery degrades to vector-only, no crash | 2 (self-check), 3 (`_lexical_candidates`) |
| Both self-checks (`fuse`, `build_tsquery`) | 2 |
| Phase A exit criterion | 6, step 5 |

No gaps.

**Placeholder scan:** The `X%` cells in Task 6 step 3 are measurement outputs that cannot exist before the code runs — the step names exactly which command produces them. Every code step contains complete, runnable code.

**Type consistency:** `SearchHit.score` is defined in Task 3 step 1 and consumed identically in Task 3 (`_to_hits`), Task 4 (`hit.file_path`), and Task 5. `build_tsquery` and `fuse` signatures in Task 2 match their call sites in Task 3. `repo_exists` is defined in Task 3 and used in both Task 3 and Task 4. `TEXT_SEARCH_CONFIG` is defined in Task 1 and imported in Task 3.
