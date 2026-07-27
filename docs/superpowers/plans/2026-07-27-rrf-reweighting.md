# RRF Reweighting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the lexical ranker more weight than the vector ranker inside RRF, then measure a three-value grid to decide whether fusion beats lexical search on both metrics or should be abandoned.

**Architecture:** `fuse()` gains an optional per-ranker weight list. `search()` passes `[1.0, LEXICAL_WEIGHT]` — vector anchored at 1.0, only the lexical weight varies. The grid is run by editing that one module constant three times and re-running the existing evaluation harness.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, PostgreSQL 16 + pgvector, FastAPI. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-27-rrf-reweighting-design.md`

## Global Constraints

- **No test framework.** This repo has no pytest and no linter. The convention is an assert-based `_self_check()` guarded by `if __name__ == "__main__":`, run with `python -m app.services.<module>`. Do not add pytest.
- Identifiers in English; code comments and user-visible strings in Spanish.
- **The vector ranker's weight stays at `1.0` and is never varied.** Two free weights would make infinitely many equivalent combinations — `(2, 3)` orders identically to `(4, 6)` — with no way to compare runs. One degree of freedom, one number to report.
- **The grid is exactly three values, fixed in advance: `1.0`, `1.5`, `2.0`.** Do not try other values, and do not stop early because one looks good. Report all three.
- **Acceptance:** the winner must reach **hit@5 > 60%** while holding **hit@1 ≥ 33%**. If none does, `/search` switches to lexical mode and the README records that fusion did not help. That outcome is a valid result, not a failure to hide.
- Existing constants stay untouched: `CANDIDATES_PER_RANKER = 30`, `RRF_K = 60`, `DOC_WEIGHT = 0.7`.
- Deliberate shortcuts carry a `repoqa:` comment naming the ceiling and the upgrade path.
- Local-only repo, no remote, never push.
- Docker must be running. If `docker compose` cannot reach the daemon, stop and report it.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/services/retrieval.py` | **Modify.** Add `LEXICAL_WEIGHT`, add the `weights` parameter to `fuse()`, pass weights from `search()`, extend `_self_check()`. All of it is one file because the weight, the fusion that uses it, and the check that proves it works change together. |
| `README.md` | **Modify.** Record the grid results and the verdict. |

Two tasks: the code change carries its own self-check and can be judged on its own; the measurement is a separate deliverable a reviewer could reject independently (for example if a number were misreported) while accepting the code.

---

### Task 1: Per-ranker weights in RRF

**Files:**
- Modify: `backend/app/services/retrieval.py`

**Interfaces:**
- Consumes: existing `RRF_K = 60`, `DOC_WEIGHT = 0.7`, `_is_doc(path) -> bool`, and `search()`'s existing `ranked_ids` construction, which orders the lists `[vector, lexical]`.
- Produces:
  - `LEXICAL_WEIGHT: float` — module constant, the only value Task 2 edits.
  - `fuse(ranked_ids: list[list[int]], paths: dict[int, str], weights: list[float] | None = None) -> list[tuple[int, float]]` — `weights` defaults to all-`1.0`, preserving the previous behaviour exactly.

- [ ] **Step 1: Write the failing self-check additions**

In `backend/app/services/retrieval.py`, inside `_self_check()`, insert these blocks immediately before the final `print("retrieval OK — tsquery y fusion RRF")` line:

```python
    # --- pesos por ranker --------------------------------------------------
    # Guarda de regresion: sin `weights`, el resultado tiene que ser identico
    # al de antes del cambio. Si esto cae, la rejilla de la fase siguiente
    # estaria midiendo dos cambios a la vez y sus numeros no serian
    # comparables con los de la fase A.
    assert fuse([[1, 2]], {1: "a.py", 2: "b.py"}) == [
        (1, 1.0 / (RRF_K + 1)),
        (2, 1.0 / (RRF_K + 2)),
    ], fuse([[1, 2]], {1: "a.py", 2: "b.py"})

    # El peso tiene que cambiar el orden de verdad. Sin esta comprobacion, una
    # implementacion que ignore `weights` pasaria desapercibida y la rejilla
    # devolveria el mismo numero tres veces sin que nadie lo note.
    #
    # 10 sale primero en la lista vectorial; 20 sale segundo en la lexica.
    # Con pesos iguales gana 10 (1/61 > 1/62). Con peso lexico 2.0 gana 20
    # (2/62 > 1/61). Se comparan posiciones relativas y no quien va primero
    # en absoluto, porque 40 empata con 10 y el empate no es lo que se mide.
    weight_paths = {10: "a.py", 20: "b.py", 40: "c.py"}
    equal_order = [chunk_id for chunk_id, _ in fuse([[10], [40, 20]], weight_paths)]
    assert equal_order.index(10) < equal_order.index(20), equal_order

    weighted_order = [
        chunk_id for chunk_id, _ in fuse([[10], [40, 20]], weight_paths, [1.0, 2.0])
    ]
    assert weighted_order.index(20) < weighted_order.index(10), weighted_order
```

- [ ] **Step 2: Run it to verify it fails**

```bash
docker compose exec -T backend python -m app.services.retrieval
```

Expected: `TypeError: fuse() takes 2 positional arguments but 3 were given` — `fuse` does not accept `weights` yet. If instead you see an `AssertionError` on the regression guard, stop and report it: that would mean the current unweighted behaviour is not what the guard describes.

- [ ] **Step 3: Add the constant**

In `backend/app/services/retrieval.py`, replace this line:

```python
DOC_WEIGHT = 0.7
```

with:

```python
DOC_WEIGHT = 0.7
# Peso del ranker lexico dentro de RRF; el vectorial queda fijo en 1.0. Con
# pesos iguales un fragmento solo-vectorial en posicion 1 (1/61) le gana a uno
# solo-lexico en posicion 5 (1/65), y el vectorial acierta 0% en @1 por si
# solo: su cabeza es ruido desplazando aciertos reales.
# repoqa: constante fija, no configurable. Se calibra editandola y corriendo
# la evaluacion. Si algun dia hay que calibrar por repositorio, ahi se
# justifica moverla a configuracion.
LEXICAL_WEIGHT = 1.0
```

- [ ] **Step 4: Add the `weights` parameter to `fuse`**

Replace the whole `fuse` function with:

```python
def fuse(
    ranked_ids: list[list[int]],
    paths: dict[int, str],
    weights: list[float] | None = None,
) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion sobre varias listas ordenadas por relevancia.

    Cada documento suma `peso / (RRF_K + posicion)` por cada lista donde
    aparece. Se usan las *posiciones* y no los puntajes porque la distancia
    coseno (0 a 2) y ts_rank_cd (sin cota superior) viven en escalas
    incomparables: normalizarlas exigiria calibrar, los rankings no.

    `weights` da un peso por lista, en el mismo orden que `ranked_ids`. Sin el,
    todas pesan 1.0 y el resultado es identico al de la fusion sin pesos.

    DOC_WEIGHT se aplica antes de que el llamador recorte a top_k — penalizar
    una lista ya truncada no cambiaria que documentos sobreviven.
    """
    if weights is None:
        weights = [1.0] * len(ranked_ids)

    scores: dict[int, float] = {}
    for ranked, weight in zip(ranked_ids, weights):
        for position, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (RRF_K + position)

    for chunk_id in scores:
        if _is_doc(paths[chunk_id]):
            scores[chunk_id] *= DOC_WEIGHT

    return sorted(scores.items(), key=lambda pair: -pair[1])
```

- [ ] **Step 5: Pass the weights from `search`**

In `backend/app/services/retrieval.py`, inside `search()`, replace this line:

```python
    fused = fuse(ranked_ids, paths)
```

with:

```python
    # El orden coincide con ranked_ids: vectorial primero, lexico segundo.
    fused = fuse(ranked_ids, paths, [1.0, LEXICAL_WEIGHT])
```

- [ ] **Step 6: Run the self-check to verify it passes**

```bash
docker compose exec -T backend python -m app.services.retrieval
```

Expected: `retrieval OK — tsquery y fusion RRF`

- [ ] **Step 7: Verify the default weight changed nothing end to end**

`LEXICAL_WEIGHT` is still `1.0`, so the hybrid numbers must be exactly what phase A recorded — 5/15 hit@1 and 8/15 hit@5:

```bash
docker compose exec -T backend python -m app.services.evaluate eval/uswap.json hybrid
```

Expected: `acierto@1:  5/15 (33%)` and `acierto@5:  8/15 (53%)`. Any other number means the refactor changed behaviour it was not supposed to change — stop and report it rather than continuing to the grid.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/retrieval.py
git commit -m "feat: per-ranker weights in RRF fusion, lexical weight at 1.0"
```

---

### Task 2: Run the grid and record the verdict

**Files:**
- Modify: `backend/app/services/retrieval.py` (the `LEXICAL_WEIGHT` value only)
- Modify: `README.md`

**Interfaces:**
- Consumes: `LEXICAL_WEIGHT` and the weighted `fuse()` from Task 1.
- Produces: the recorded measurement and the decision about whether `/search` keeps hybrid mode.

- [ ] **Step 1: Measure `LEXICAL_WEIGHT = 1.0` (control)**

The constant is already `1.0` from Task 1. Run:

```bash
docker compose exec -T backend python -m app.services.evaluate eval/uswap.json hybrid
```

Record `acierto@1` and `acierto@5` exactly as printed. This must match phase A (5/15, 8/15); it is the control that proves the grid moves only because of the weight.

- [ ] **Step 2: Measure `LEXICAL_WEIGHT = 1.5`**

In `backend/app/services/retrieval.py`, change `LEXICAL_WEIGHT = 1.0` to:

```python
LEXICAL_WEIGHT = 1.5
```

```bash
docker compose exec -T backend python -m app.services.evaluate eval/uswap.json hybrid
```

Record both numbers exactly as printed.

- [ ] **Step 3: Measure `LEXICAL_WEIGHT = 2.0`**

In `backend/app/services/retrieval.py`, change `LEXICAL_WEIGHT = 1.5` to:

```python
LEXICAL_WEIGHT = 2.0
```

```bash
docker compose exec -T backend python -m app.services.evaluate eval/uswap.json hybrid
```

Record both numbers exactly as printed.

- [ ] **Step 4: Confirm the other two modes did not move**

The `vector` and `lexical` modes never call `fuse()`, so they must be byte-identical to phase A regardless of the weight:

```bash
docker compose exec -T backend python -m app.services.evaluate eval/uswap.json vector
```

Expected: `acierto@1:  0/15 (0%)`, `acierto@5:  4/15 (26%)`

```bash
docker compose exec -T backend python -m app.services.evaluate eval/uswap.json lexical
```

Expected: `acierto@1:  2/15 (13%)`, `acierto@5:  9/15 (60%)`

Any movement here is a bug, not a result. Stop and report it.

- [ ] **Step 5: Apply the acceptance criterion and set the final weight**

The criterion is **hit@5 > 60% AND hit@1 ≥ 33%** — the winner must beat lexical-only on coverage without losing the hybrid's first-result advantage.

- If one or more grid values meet it, set `LEXICAL_WEIGHT` to the best such value and leave `/search` in hybrid mode.
- If none meets it, set `LEXICAL_WEIGHT` back to the value that scored best overall, and change the default in `backend/app/schemas/repo.py` from `mode: SearchMode = "hybrid"` to `mode: SearchMode = "lexical"`, so the API serves the configuration that actually measures best. Add this comment above that field:

```python
    # La fusion no supero al lexico solo en acierto@5 con ningun peso de la
    # rejilla (ver Resultados de recuperacion en el README). Se sirve el modo
    # que mide mejor; "hybrid" sigue disponible para seguir experimentando.
```

- [ ] **Step 6: Record the grid in the README**

In `README.md`, inside the `## Resultados de recuperación` section, add this table immediately after the existing three-mode table, filling in the measured values:

```markdown
### Reponderación de la fusión

El ranker vectorial pesa `1.0` fijo; solo varía el peso del léxico. Los tres valores
se fijaron antes de medir, y se reportan los tres.

| Peso léxico | acierto@1 | acierto@5 |
|---|---|---|
| 1.0 (control) | X% | X% |
| 1.5 | X% | X% |
| 2.0 | X% | X% |
```

Then write one paragraph in Spanish stating plainly which value won, whether it met the
**@5 > 60% con @1 ≥ 33%** criterion, and what `/search` now serves by default.

**If the winner is `2.0`, the highest value in the grid, say explicitly that this means the vector
ranker contributes little — not that the fusion succeeded.** A rising lexical weight makes the
fusion converge toward pure lexical search; reading that as a win for fusion would be self-deception.
Also note that the grid's edge won, so the true optimum may lie beyond `2.0` and was not explored.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/retrieval.py backend/app/schemas/repo.py README.md
git commit -m "perf: tune RRF lexical weight, record the grid"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `weights` parameter on `fuse()`, defaulting to all-1.0 | 1, step 4 |
| `search()` passes `[1.0, LEXICAL_WEIGHT]` in ranked_ids order | 1, step 5 |
| Vector anchored at 1.0, never varied | 1 step 5 (hardcoded), Global Constraints |
| `LEXICAL_WEIGHT` as a plain module constant, not env var or parameter | 1, step 3 |
| Grid of exactly 1.0 / 1.5 / 2.0, declared in advance | 2, steps 1-3 + Global Constraints |
| All three reported regardless of winner | 2, step 6 |
| Regression guard: unweighted `fuse` unchanged | 1, step 1 (assert) + step 7 (end-to-end) |
| Effect check: a weight actually reorders | 1, step 1 |
| `vector` and `lexical` modes unchanged | 2, step 4 |
| Acceptance: @5 > 60% and @1 ≥ 33% | 2, step 5 |
| Fall back to lexical mode if criterion unmet | 2, step 5 |
| README states "weight 2.0 winning means vector contributes little" | 2, step 6 |

No gaps.

**Placeholder scan:** The `X%` cells in Task 2 step 6 are measurement outputs that cannot exist before the commands run; the steps that produce them are named immediately above. Every code step contains complete, runnable code.

**Type consistency:** `fuse(ranked_ids, paths, weights)` in Task 1 step 4 matches its three call sites — the two self-check calls in step 1 and the `search()` call in step 5. `LEXICAL_WEIGHT` is defined in step 3, used in step 5, and is the only value Task 2 edits. `RRF_K` and `DOC_WEIGHT` are referenced but not redefined, matching their existing declarations.
