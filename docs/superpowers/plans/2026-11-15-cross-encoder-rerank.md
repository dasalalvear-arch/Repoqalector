# Cross-Encoder Reranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `rerank` search mode that reorders the hybrid candidate pool with a cross-encoder, measure three pre-declared models against the eval set, and adopt one only if the pre-fixed decision rule says so.

**Architecture:** `retrieval.search()` builds the fused pool exactly as `hybrid` does; in `rerank` mode the whole pool (untruncated) goes through `rerank.rerank()`, which scores every (question, fragment) pair with a `CrossEncoder` and returns them sorted, and only then is the list cut to `top_k`. The model is chosen by one setting, overridable per process with `RERANK_MODEL`, so the grid runs without editing code. `evaluate.py` gains the mode plus latency reporting.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, PostgreSQL 16 + pgvector, `sentence-transformers==3.3.1` (already installed; provides `CrossEncoder`), torch 2.5.1 CPU.

**Spec:** `docs/superpowers/specs/2026-11-15-cross-encoder-rerank-design.md`

## Global Constraints

- **No new Python or npm dependencies.** `CrossEncoder` ships with the installed `sentence-transformers`. If a model fails to load because a package is missing (for example `sentencepiece` or `protobuf`), **stop and ask the user** — do not add it, and do not record the model as "discarded".
- **No test framework.** Convention is an assert-based `_self_check()` under `if __name__ == "__main__":`, run with `python -m app.services.<module>`. Do not add pytest.
- Identifiers in English; code comments and user-visible strings in Spanish (comments without accents, like the existing code).
- **`hybrid` must not change.** `evaluate eval/uswap.json hybrid` must keep printing `acierto@1:  3/15 (20%)` and `acierto@5:  10/15 (66%)`. Any movement there is a bug.
- **The grid is fixed**: `cross-encoder/ms-marco-MiniLM-L-6-v2`, `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, `BAAI/bge-reranker-v2-m3`. Do not try other models, other pool sizes, or a document penalty. All three are reported whoever wins.
- **Decision rule, fixed before measuring:** (1) discard any model whose median latency exceeds **15 seconds** per question, or that does not load in the container — still reported, with the reason; (2) among the rest, adopt the one with the **highest acierto@5, only if it is above 10/15**; (3) tie on acierto@5 → higher acierto@1, then lower median latency. acierto@1 does not veto.
- **No silent fallback to `hybrid`.** If the model fails to load or score, the request fails visibly.
- The model must load on first use, never at import: `python -m app.services.retrieval` must pass without downloading any reranking model.
- Deliberate shortcuts carry a `repoqa:` comment naming the ceiling and the upgrade path.
- **Commits are local. Never `git push`** — the repo has a GitHub remote and pushing needs the user's explicit permission each time.
- Docker must be running. If `docker compose` cannot reach the daemon, stop and report it.
- Models download from Hugging Face on first use into the `/models` volume (90 MB, 470 MB and 2.3 GB). That is expected; it needs no key.
- `/ask` re-measurement (Task 4A) spends **15 Gemini calls out of a 20/day free quota**. Run it once. If it stops on a `429`, the harness has saved what it generated: report the partial state and do not write numbers into the README.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/core/config.py` | **Modify.** Add `rerank_model`. |
| `backend/app/services/rerank.py` | **Create.** Lazy-loaded `CrossEncoder` and `rerank()`. Holds its own self-check. |
| `backend/app/services/retrieval.py` | **Modify.** `rerank` mode in `search()`. |
| `backend/app/schemas/repo.py` | **Modify.** `SearchMode` accepts `rerank`; default changes only on adoption. |
| `backend/app/services/evaluate.py` | **Modify.** Accept `rerank`, report latency and how often a doc ranks first. |
| `backend/eval/results/*.txt` | **Create.** Raw output of each measured run, so an interrupted grid resumes without re-running. |
| `backend/app/services/synthesis.py` | **Modify only on adoption.** `/ask` retrieves with `rerank`. |
| `backend/eval/uswap.answers.json` | **Regenerated only on adoption.** |
| `README.md`, `CLAUDE.md`, spec | **Modify.** Results and verdict. |

---

### Task 1: The reranker

**Files:**
- Modify: `backend/app/core/config.py`
- Create: `backend/app/services/rerank.py`

**Interfaces:**
- Produces: `settings.rerank_model: str`
- Produces: `rerank.rerank(question: str, chunks: list[CodeChunk]) -> list[tuple[CodeChunk, float]]` — every chunk, sorted by score descending (higher = better). Empty input returns `[]` without loading the model.

- [ ] **Step 1: Add the setting**

In `backend/app/core/config.py`, add inside `class Settings`, after `judge_model`:

```python
    # Cross-encoder que reordena el pool hibrido en modo "rerank". Se descarga
    # de Hugging Face la primera vez que se usa. Para medir otro modelo sin
    # tocar codigo: `docker compose exec -e RERANK_MODEL=<modelo> backend ...`.
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
```

- [ ] **Step 2: Write the module with the self-check and a stub**

Create `backend/app/services/rerank.py`:

```python
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


def rerank(question: str, chunks: list[CodeChunk]) -> list[tuple[CodeChunk, float]]:
    raise NotImplementedError


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
```

- [ ] **Step 3: Run it to see it fail**

Run: `docker compose exec backend python -m app.services.rerank`
Expected: `NotImplementedError`.

- [ ] **Step 4: Implement**

Replace the stub `rerank` in `backend/app/services/rerank.py` with:

```python
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
```

- [ ] **Step 5: Run the self-check**

Run: `docker compose exec backend python -m app.services.rerank`
Expected: a one-time download of ~90 MB, then `rerank OK — cross-encoder/ms-marco-MiniLM-L-6-v2`.

If the order assert fails with this English-only model on the Spanish question, **do not change the assert or the question.** Run the check with the multilingual model instead:

```bash
docker compose exec -e RERANK_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 backend python -m app.services.rerank
```

If that passes, the code is correct and the control model simply cannot rank Spanish against code — note it for the README (Task 3 will measure it anyway) and continue. If both fail, the bug is in `rerank()`.

- [ ] **Step 6: Confirm nothing else pays for the model**

Run: `docker compose exec backend python -m app.services.retrieval`
Expected: `retrieval OK — tsquery y fusion RRF`, with no download or model-loading output.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/config.py backend/app/services/rerank.py
git commit -m "feat: cross-encoder reranker with a lazy-loaded model"
```

---

### Task 2: `rerank` mode in search, and latency in the evaluation

**Files:**
- Modify: `backend/app/services/retrieval.py`
- Modify: `backend/app/schemas/repo.py`
- Modify: `backend/app/services/evaluate.py`

**Interfaces:**
- Consumes: `rerank.rerank(question, chunks) -> list[tuple[CodeChunk, float]]`, `settings.rerank_model`
- Produces: `retrieval.search(db, repo, question, top_k, "rerank") -> list[SearchHit]`; `SearchMode` includes `"rerank"`; `evaluate` CLI accepts `rerank` and prints two extra lines (`doc en el primer puesto`, `latencia`)

- [ ] **Step 1: Add the mode to `search()`**

In `backend/app/services/retrieval.py`, change the services import to:

```python
from app.services import rerank
from app.services.embeddings import embed_one
```

In `search()`, update the docstring and replace the last two lines (the `fused = ...` line and the `return`) with:

```python
    """Busqueda semantica, lexica, fusionada o fusionada y reordenada.

    `mode` existe para poder medir cada etapa por separado en la evaluacion:
    "vector" y "lexical" son las dos mitades, "hybrid" su fusion, y "rerank" la
    fusion reordenada por un cross-encoder.
    """
```

```python
    # El orden coincide con ranked_ids: vectorial primero, lexico segundo.
    fused = fuse(ranked_ids, paths, [1.0, LEXICAL_WEIGHT])
    if mode == "rerank":
        # El pool entero, sin recortar: cortar antes dejaria fuera justo los
        # fragmentos enterrados que el reranker viene a rescatar. DOC_WEIGHT ya
        # no influye aqui, porque el orden lo decide el cross-encoder.
        pool = [by_id[chunk_id] for chunk_id, _ in fused]
        return _to_hits(rerank.rerank(question, pool), top_k)
    return _to_hits([(by_id[chunk_id], score) for chunk_id, score in fused], top_k)
```

(The existing comment line `# El orden coincide con ranked_ids...` is already there — keep one copy, not two.)

- [ ] **Step 2: Accept the mode over HTTP**

In `backend/app/schemas/repo.py`, change:

```python
SearchMode = Literal["vector", "lexical", "hybrid", "rerank"]
```

and replace the comment above `score: float` in `SearchHit` with:

```python
    # Mayor es mejor, en todos los modos. No es una distancia: el puntaje de
    # RRF no tiene unidad, en modo vectorial se reporta 1 - distancia_coseno, y
    # en modo rerank es el puntaje del cross-encoder. La direccion es siempre
    # la misma para que las comparaciones no se inviertan.
```

The default of `SearchRequest.mode` stays `"hybrid"` in this task.

- [ ] **Step 3: Teach the evaluation the mode, the latency and the doc count**

In `backend/app/services/evaluate.py`, change the imports to:

```python
import json
import statistics
import sys
import time
from pathlib import Path

from app.core.config import settings
from app.core.database import SessionLocal
from app.services import retrieval
```

Change `VALID_MODES` and its comment to:

```python
# `retrieval.search()` solo reconoce estos valores; cualquier otra cosa (p.ej.
# un typo como "hibrid") cae en el fallback silencioso a hybrid dentro de esa
# funcion, midiendo hybrid pero imprimiendo el nombre equivocado. Sin esta
# validacion la medicion quedaria mal etiquetada sin ningun error.
VALID_MODES = ("vector", "lexical", "hybrid", "rerank")
```

Replace the body of `evaluate()` from `print(f"\nRepo:  {repo}")` down to the final `return` with:

```python
        label = f"{mode} [{settings.rerank_model}]" if mode == "rerank" else mode
        print(f"\nRepo:  {repo}")
        print(f"Modo:  {label} | Preguntas: {len(questions)} | top_k={TOP_K}\n")

        # Calentamiento: cargar el modelo (y descargarlo la primera vez) no es
        # latencia de una pregunta. Sin esto, la primera fila cargaria con todo.
        retrieval.search(db, repo, questions[0][0], TOP_K, mode)

        hits_at_1 = hits_at_k = docs_first = 0
        latencies: list[float] = []
        for question, expected in questions:
            start = time.perf_counter()
            hits = retrieval.search(db, repo, question, TOP_K, mode)
            latencies.append(time.perf_counter() - start)

            paths = [hit.file_path for hit in hits]
            rank = next(
                (i + 1 for i, path in enumerate(paths) if any(e in path for e in expected)),
                None,
            )

            hits_at_1 += rank == 1
            hits_at_k += rank is not None
            # Cuantas veces gana la prosa: es el modo de falla conocido de la
            # recuperacion, y hay que saber si el reranker lo repite.
            docs_first += bool(paths) and paths[0].lower().endswith(retrieval.DOC_EXTENSIONS)
            mark = "OK   " if rank == 1 else ("top5 " if rank else "FALLA")
            detail = f"rank {rank}" if rank else f"trajo {paths[0] if paths else '(nada)'}"
            print(f"  {mark} {question[:50]:<50} -> {expected[0]:<22} {detail}")
    finally:
        db.close()

    total = len(questions)
    print(f"\n  acierto@1:  {hits_at_1}/{total} ({100 * hits_at_1 // total}%)")
    print(f"  acierto@{TOP_K}:  {hits_at_k}/{total} ({100 * hits_at_k // total}%)")
    print(f"  doc en el primer puesto: {docs_first}/{total}")
    print(f"  latencia:   mediana {statistics.median(latencies):.2f}s | max {max(latencies):.2f}s\n")
    return hits_at_k / total
```

Also add `rerank` to the module docstring's examples:

```python
    docker compose exec backend python -m app.services.evaluate eval/uswap.json rerank
```

- [ ] **Step 4: Regression — `hybrid` is untouched**

Run: `docker compose exec backend python -m app.services.evaluate eval/uswap.json hybrid`
Expected: `acierto@1:  3/15 (20%)`, `acierto@5:  10/15 (66%)`, then the two new lines. If either number moved, the change to `search()` altered the hybrid path — fix that before continuing.

Run: `docker compose exec backend python -m app.services.retrieval`
Expected: `retrieval OK — tsquery y fusion RRF`

- [ ] **Step 5: The new mode runs end to end**

```bash
curl -s -X POST localhost:8000/search -H "Content-Type: application/json" -d '{"repo":"dasalalvear-arch/u-swap","question":"que algoritmo se usa para hashear las contrasenas","mode":"rerank"}' | python -c "import sys, json; hits = json.load(sys.stdin); print(len(hits), [h['score'] for h in hits]); assert len(hits) == 5 and [h['score'] for h in hits] == sorted((h['score'] for h in hits), reverse=True)"
```

Expected: `5` and five scores in descending order. (The backend reloads on file change; the first request loads the model and takes a few seconds.)

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/search -H "Content-Type: application/json" -d '{"repo":"dasalalvear-arch/u-swap","question":"x","mode":"hibrid"}'
```

Expected: `422` — a typo in the mode is still rejected at the HTTP layer.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/retrieval.py backend/app/schemas/repo.py backend/app/services/evaluate.py
git commit -m "feat: rerank search mode, with latency reported by the evaluation"
```

---

### Task 3: Run the grid and apply the decision rule

**Files:**
- Create: `backend/eval/results/hybrid.txt`, `backend/eval/results/rerank-ms-marco-MiniLM-L-6-v2.txt`, `backend/eval/results/rerank-mmarco-mMiniLMv2-L12-H384-v1.txt`, `backend/eval/results/rerank-bge-reranker-v2-m3.txt`

**Interfaces:**
- Consumes: the `evaluate` CLI from Task 2
- Produces: four result files and one verdict — either `ADOPT <model id>` or `NO ADOPTION` — which selects Task 4A or Task 4B

Each run is saved as it finishes. If the session is interrupted, **rerun only the runs whose file is missing or has no `latencia:` line.**

- [ ] **Step 1: Baseline on this machine**

```bash
docker compose exec -T backend sh -c 'mkdir -p eval/results && python -m app.services.evaluate eval/uswap.json hybrid | tee eval/results/hybrid.txt'
```

Expected: `3/15`, `10/15`, and a median latency well under a second. This latency is what the reranker's is compared against.

- [ ] **Step 2: Control model (English only, ~90 MB)**

```bash
docker compose exec -T -e RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2 backend sh -c 'python -m app.services.evaluate eval/uswap.json rerank | tee eval/results/rerank-ms-marco-MiniLM-L-6-v2.txt'
```

- [ ] **Step 3: Small multilingual model (~470 MB download)**

```bash
docker compose exec -T -e RERANK_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 backend sh -c 'python -m app.services.evaluate eval/uswap.json rerank | tee eval/results/rerank-mmarco-mMiniLMv2-L12-H384-v1.txt'
```

- [ ] **Step 4: Large multilingual model (~2.3 GB download)**

Run this one **in the background** — on CPU it may take tens of seconds per question, plus the download:

```bash
docker compose exec -T -e RERANK_MODEL=BAAI/bge-reranker-v2-m3 backend sh -c 'python -m app.services.evaluate eval/uswap.json rerank | tee eval/results/rerank-bge-reranker-v2-m3.txt'
```

For any of Steps 2–4: if the process dies while loading (killed for memory, or a load error), the result file will be empty or cut short and the error is on stderr. Write one line into that file saying so, for example `NO CARGO: Killed (memoria del contenedor)`, and treat the model as discarded by rule 1. **Exception:** a missing Python package is not a discard — stop and ask the user (Global Constraints).

- [ ] **Step 5: Read the four files and fill the table**

```bash
tail -n 6 backend/eval/results/*.txt
```

Build this table from the files (no number from memory):

| Configuración | acierto@1 | acierto@5 | doc primero | latencia mediana | latencia máx. |
|---|---|---|---|---|---|
| Híbrido (sin reranking) | | | | | |
| `ms-marco-MiniLM-L-6-v2` | | | | | |
| `mmarco-mMiniLMv2-L12-H384-v1` | | | | | |
| `bge-reranker-v2-m3` | | | | | |

And, per reranking model, the rank it gave to the three rescuable questions (they print as `rank N` or `FALLA` in each file):

- `como se filtra el catalogo por categoria` (was 31 in the pool)
- `donde se configura la conexion a la base de datos` (was 32)
- `donde se decide si un usuario es admin` (was 9)

- [ ] **Step 6: Apply the rule, mechanically**

1. Strike every model with median latency above 15.00 s, and every model that did not load.
2. Of the rest, take the highest acierto@5. If it is 10/15 or lower: verdict `NO ADOPTION`.
3. Otherwise that model wins. Tie on acierto@5 → higher acierto@1 → lower median latency. Verdict `ADOPT <model id>`.

Do not adjust the rule to the numbers. A model at 11/15 is adopted even though 80% (12/15) is not reached; the README says both things.

- [ ] **Step 7: Commit the evidence**

Put the filled table and the verdict in the commit body.

```bash
git add backend/eval/results
git commit -m "eval: reranking grid over three cross-encoders

<the table from Step 5>

Veredicto: <ADOPT model id | NO ADOPTION>"
```

**Then do Task 4A if the verdict is `ADOPT`, or Task 4B if it is `NO ADOPTION`. Never both.**

---

### Task 4A: Adopt the winning model (only if the verdict is `ADOPT`)

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/schemas/repo.py`
- Modify: `backend/app/services/synthesis.py:80`
- Modify: `backend/app/services/evaluate.py`
- Regenerate: `backend/eval/uswap.answers.json`
- Modify: `frontend/src/services/api.ts`
- Modify: `README.md`, `CLAUDE.md`, `docs/superpowers/specs/2026-11-15-cross-encoder-rerank-design.md:4`

**Interfaces:**
- Consumes: the verdict and table from Task 3; `evaluate_ask` CLI (`python -m app.services.evaluate_ask eval/uswap.json`)
- Produces: `/search` and `/ask` serving `rerank` by default

- [ ] **Step 1: Make the winner the default model**

In `backend/app/core/config.py`, set `rerank_model` to the winning model id and replace its comment with one that states the measured result, in this shape (real numbers from Task 3):

```python
    # Cross-encoder que reordena el pool hibrido; es lo que sirven /search y
    # /ask. Elegido por medicion entre tres modelos: <X>/15 en acierto@5 contra
    # 10/15 del hibrido, con <N> s de latencia mediana en CPU. Cambiarlo obliga
    # a volver a medir: `docker compose exec -e RERANK_MODEL=<modelo> backend
    # python -m app.services.evaluate eval/uswap.json rerank`.
    rerank_model: str = "<winning model id>"
```

- [ ] **Step 2: Serve `rerank`**

In `backend/app/schemas/repo.py`, replace the comment and default of `SearchRequest.mode` (real numbers from Task 3):

```python
    # El modo que se sirve es el hibrido reordenado por cross-encoder: <X>/15
    # en acierto@5 contra 10/15 del hibrido solo. Los otros tres existen para
    # medir cada etapa por separado.
    mode: SearchMode = "rerank"
```

In `backend/app/services/synthesis.py`, line 80, change the mode:

```python
    hits = retrieval.search(db, repo, question, top_k, "rerank")
```

In `backend/app/services/evaluate.py`, make the CLI default match what is served — change both the signature and the `__main__` fallback:

```python
def evaluate(eval_path: Path, mode: str = "rerank") -> float:
```

```python
    evaluate(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "rerank")
```

In `frontend/src/services/api.ts`, update the comment on `SearchHit`:

```ts
/** Un fragmento recuperado. `score`: mayor es mejor, en todos los modos. */
```

- [ ] **Step 3: Verify the served path**

```bash
docker compose exec backend python -m app.services.rerank
docker compose exec backend python -m app.services.retrieval
docker compose exec backend python -m app.services.synthesis
docker compose exec backend python -m app.services.evaluate eval/uswap.json
docker compose exec backend python -m app.services.evaluate eval/uswap.json hybrid
cd frontend && npm run build
```

Expected: three `OK` lines (the first naming the winning model); the no-argument evaluate prints `Modo:  rerank [<winner>]` and the same acierto@5 as its Task 3 file; `hybrid` still prints `3/15` and `10/15`; a clean build.

- [ ] **Step 4: Re-measure `/ask` (15 Gemini calls — run once)**

The saved answers were generated from the old top-5, and the harness cannot detect a retrieval change on its own. Keep the old numbers for the README first — they are: respondió cuando debía 9/10, se abstuvo cuando debía 2/5, citas inválidas 1, fundamentadas 11/12.

```bash
rm backend/eval/uswap.answers.json
docker compose exec -T backend python -m app.services.evaluate_ask eval/uswap.json
```

Run it in the background; it pauses 13 s between questions and each one now also reranks. Expected: 15 lines and four metrics, with no `PARCIAL` line.

If it prints `Detenido en ...` (quota), the generated answers are saved. **Do not write `/ask` numbers into the README.** Say in the final report that `/ask` re-measurement is partial and that rerunning the same command tomorrow completes it; finish the remaining steps with the `/ask` "después" column marked `pendiente (cuota)`.

- [ ] **Step 5: README**

In the status table, replace the `/search` row's parenthetical with the new numbers, and keep the sentence about the 80% target truthful (reached or not).

After the "Reponderación de la fusión" subsection, add `### Reranking con cross-encoder` containing:

- the measurement that motivated it: 3 of the 5 failing questions had the right file in the pool at ranks 9, 31 and 32; 2 were not in the pool; ceiling 13/15;
- the full table from Task 3 (all four rows), stating that the three models were fixed before measuring;
- what happened to each of the three rescuable questions under the winner;
- the decision rule and the verdict;
- how often a doc ranked first, hybrid vs winner;
- the caveats, in these terms: choosing the best of three models on 15 questions inflates the winner's number, and one question of difference between models does not separate them; latency is one CPU machine; the two questions absent from the pool are untouched and widening `CANDIDATES_PER_RANKER` is the next step;
- the reproduce command: `docker compose exec -e RERANK_MODEL=<modelo> backend python -m app.services.evaluate eval/uswap.json rerank`.

Replace the old closing sentence "El siguiente paso natural es el reranking con cross-encoder." with a pointer to the new subsection.

In "Resultados de `/ask`", change the intro to say the fragments come from the reranked mode, and turn the table into before/after columns (hybrid → rerank) using the numbers from Step 4.

In "Uso", extend the note about the first search being slow: the reranking model also downloads on first use (give its size).

In "Verificaciones", add:

```bash
docker compose exec backend python -m app.services.rerank     # el cross-encoder ordena bien un par trivial
```

- [ ] **Step 6: CLAUDE.md and the spec**

In `CLAUDE.md`:
- Pipeline block: `POST /search  → embed question → vector + lexical search → RRF fusion → cross-encoder rerank → chunks     [DONE]`.
- "Current state": the next open item is widening the candidate pool for the two questions the pool never contains — no longer reranking.
- The "Retrieval is hybrid…" paragraph: add the reranked numbers and the winning model, keep the sentence that says to run the eval before changing anything.
- "Measuring": the command with `rerank`, the note that `evaluate` with no mode measures what is served, and that `backend/eval/results/` holds the raw grid output.
- The `/ask` numbers under "Measuring": replace with the Step 4 results.
- Backend section, `retrieval.py` paragraph: four modes; `rerank` reorders the whole untruncated pool through `services/rerank.py`; the model is lazy-loaded and there is deliberately no fallback to `hybrid`.
- The `EMBEDDING_DIM` paragraph: add one sentence that the reranking model, unlike the embedding model, can be swapped without reindexing — but not without re-measuring.

Change line 4 of the spec to `**Estado:** implementado y adoptado — <winning model id> (plan: docs/superpowers/plans/2026-11-15-cross-encoder-rerank.md)`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/config.py backend/app/schemas/repo.py backend/app/services/synthesis.py backend/app/services/evaluate.py backend/eval/uswap.answers.json frontend/src/services/api.ts README.md CLAUDE.md docs/superpowers/specs/2026-11-15-cross-encoder-rerank-design.md
git commit -m "feat: serve reranked retrieval in /search and /ask

<acierto@1 and acierto@5 before and after, winning model, median latency,
and the four /ask metrics before and after>"
```

Do not push.

---

### Task 4B: Record the negative result (only if the verdict is `NO ADOPTION`)

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `README.md`, `CLAUDE.md`, `docs/superpowers/specs/2026-11-15-cross-encoder-rerank-design.md:4`

**Interfaces:**
- Consumes: the verdict and table from Task 3
- Produces: documentation only. `/search` and `/ask` keep serving `hybrid`; `rerank` stays available as a measuring mode, like `vector` and `lexical`. `/ask` is not re-measured.

- [ ] **Step 1: Say in the code why it is not the default**

In `backend/app/core/config.py`, replace the comment on `rerank_model` (real numbers from Task 3):

```python
    # Cross-encoder del modo "rerank", que es solo un instrumento de medicion:
    # ninguno de los tres modelos medidos supero al hibrido (10/15 en
    # acierto@5) dentro de 15 s de latencia, asi que /search y /ask sirven
    # "hybrid". Resultados en el README y en backend/eval/results/.
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
```

- [ ] **Step 2: README**

After the "Reponderación de la fusión" subsection, add `### Reranking con cross-encoder` containing: the pool measurement (ranks 9, 31, 32; two absent; ceiling 13/15); the full four-row table from Task 3; what happened to the three rescuable questions under each model; the decision rule and the verdict that no model was adopted and why (below 10/15, over 15 s, or did not load — per model); how often a doc ranked first; and the reproduce command. State plainly that reranking did not help here, and what that suggests as the next step (widening the pool, or a code-specific model outside this grid).

Replace the old closing sentence "El siguiente paso natural es el reranking con cross-encoder." with a pointer to the new subsection. In the status table, leave the `/search` numbers as they are.

- [ ] **Step 3: CLAUDE.md and the spec**

In `CLAUDE.md`: "Current state" says reranking was measured and not adopted, with the one-line reason; the `retrieval.py` paragraph lists four modes and says `rerank` is a measuring instrument that is not served; "Measuring" mentions `backend/eval/results/`.

Change line 4 of the spec to `**Estado:** implementado, no adoptado — ningún modelo de la rejilla superó al híbrido (plan: docs/superpowers/plans/2026-11-15-cross-encoder-rerank.md)`.

- [ ] **Step 4: Final verification**

```bash
docker compose exec backend python -m app.services.retrieval
docker compose exec backend python -m app.services.evaluate eval/uswap.json hybrid
cd frontend && npm run build
```

Expected: `retrieval OK`, `3/15` and `10/15`, and a clean build.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py README.md CLAUDE.md docs/superpowers/specs/2026-11-15-cross-encoder-rerank-design.md
git commit -m "docs: reranking measured and not adopted — results and why"
```

Do not push.
