# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

RepoQA (provisional name): a RAG assistant that answers natural-language questions about a code
repository, **citing the file and line range** each answer came from. Index a repo, ask a question,
get an answer you can verify. Spanish-facing UI, English identifiers, Spanish code comments.

Monorepo: `backend/` (FastAPI) + `frontend/` (React/Vite). PostgreSQL + pgvector via Docker Compose.

This codebase is a **repurposed copy of U-Swap**, a student marketplace. The marketplace domain
(auth, items, matches, chat, admin) has been deleted; what survives is the infrastructure shape —
Docker setup, FastAPI layout, the Axios client, and the CSS. If you find a stray `uswap` reference,
it is leftover, not intentional.

## Commands

```bash
docker compose up --build      # db + backend:8000 + frontend:5173, API docs at :8000/docs
docker compose down -v         # -v also wipes the Postgres volume (fresh DB)
docker compose logs backend    # also: frontend, db
```

Frontend typecheck — **the only automated check in the repo**, run it before committing:
```bash
cd frontend && npm run build   # tsc -b && vite build
```

There is no test suite and no linter. When you add non-trivial backend logic (chunking, retrieval),
leave one runnable check behind rather than building a test framework.

## Architecture

### The RAG pipeline (what actually matters)

```
POST /repos   → clone → filter files → chunk → embed → INSERT code_chunks
POST /search  → embed question → vector + lexical search → RRF fusion → chunks     [DONE]
POST /ask     → /search → prompt with numbered chunks → LLM → {answer, sources}    [NOT BUILT]
```

**Current state:** ingestion and retrieval work and are measured. `/ask` is designed and approved but
not implemented — see `docs/superpowers/specs/2026-07-27-ask-endpoint-design.md`. The status table in
`README.md` is the authority on what exists.

**Retrieval is hybrid, and the numbers matter more than the code here.** Vector search alone scored
0% hit@1 / 26% hit@5 on the eval set; lexical alone 13% / 60%; the fused ranker with
`LEXICAL_WEIGHT = 2.0` reaches 20% / 66%. A general-purpose embedding model matches
natural-language questions to raw code poorly, and Spanish prose docs outrank the code the question
is actually about — the lexical half supplies the exact anchors (`utem.cl`, `bcrypt`) that appear
literally in the source. **Before changing anything in retrieval, run the eval and keep the number.**

### Measuring (do this before and after any retrieval change)

```bash
docker compose exec backend python -m app.services.evaluate eval/uswap.json hybrid   # also: vector, lexical
```

The question set is data, not code: `backend/eval/uswap.json`, 15 questions whose correct answer was
verified by hand, several accepting more than one valid file. `evaluate.py` calls the real
`retrieval.search()` rather than reimplementing ranking — a parallel implementation would drift and
the measured number would stop being the one users experience.

### Data model
One table, `code_chunks` (`models/chunk.py`). `file_path` + `line_start`/`line_end` are not
bookkeeping — they are the citation shown to the user, and the whole point of the product. An answer
without a verifiable source is the failure mode this project exists to avoid.

`EMBEDDING_DIM = 384` matches `all-MiniLM-L6-v2`. **Changing the embedding model changes this
number and invalidates every stored vector** — old and new embeddings are not comparable, so a model
switch means reindexing everything.

There is no `repos` table: `SELECT DISTINCT repo` backs the frontend's repo selector.

### Backend (`backend/app/`)
FastAPI layered layout: `models/`, `schemas/`, `api/routes/`, `services/`. `core/` holds `config.py`
(pydantic-settings) and `database.py` (engine + `get_db` session dependency).

`services/retrieval.py` holds all search logic — query building, both rankers, RRF fusion, and the
three modes (`vector`, `lexical`, `hybrid`). Routes are thin HTTP wrappers over it; `/search`'s only
job beyond delegating is turning an unknown repo into a 404. Keep it that way, and note that
`search()` accepts `mode` as a plain `str` and falls through to hybrid on an unrecognized value —
callers that bypass the HTTP layer must validate it themselves, which `evaluate.py` does.

`code_chunks.search_vector` is a **generated** column (`Computed(..., persisted=True)`): Postgres
maintains it, so ingestion never touches it and it cannot drift from `content`.

**Startup in `main.py`** runs at import time: `CREATE EXTENSION IF NOT EXISTS vector` must execute
**before** `create_all()`, or the `CREATE TABLE` fails with `type "vector" does not exist`. The
`from app.models import chunk` import exists solely to register the model with `Base` before
`create_all` runs — do not "clean it up".

There are **no migrations**. The project starts from a clean DB, so `create_all` suffices; if you
change a column on an existing DB, `docker compose down -v` is the intended reset.

**No authentication.** Single-user local tool. `security.py`, `limiter.py`, and `dependencies.py`
were deleted along with their dependencies (`python-jose`, `passlib`, `bcrypt`, `slowapi`). If auth
comes back, U-Swap's JWT pattern is the reference — but don't add it speculatively.

**Docker Compose reads `env_file: ./backend/.env.example`** — not `backend/.env`. Editing
`backend/.env` has no effect in Docker; edit `.env.example` or add an `environment:` override.

**API keys never go in `backend/.env.example`.** It is committed, so a real value there lives in git
history forever. The pattern already in place: `docker-compose.yml` declares
`GEMINI_API_KEY: ${GEMINI_API_KEY:-}` under `environment:`, and the real value sits in a `.env` at
the repo root, which `.gitignore` covers. `JUDGE_API_KEY` will follow the same route.

The db service must stay on `pgvector/pgvector:pg16`; the official `postgres` image lacks the
extension and startup will fail.

### Frontend (`frontend/src/`)
Single page, no router — `routes/App.tsx` renders `AskPage` directly. React Router, the PWA
(manifest + service worker), and the auth hooks were removed; don't reintroduce them for one screen.

`services/api.ts` is the Axios instance plus the shared types (`RepoSummary`, `SearchHit`, `Turn`)
that mirror the backend Pydantic schemas — update both together. `SearchHit.score` means **higher is
better** in all three modes; it is not a distance, and vector mode reports `1 - cosine_distance` so
the direction stays consistent.

`AskPage` currently calls `/search` and renders raw fragments. When `/ask` lands it switches to that
endpoint and the response shape changes from `SearchHit[]` to `{answer, found, sources}`.

`pages/AskPage.tsx` began as U-Swap's chat UI; the classes were renamed to this project's vocabulary
(`ask-layout`, `repo-row`, `answer-panel`, `thread`, `turn`, `ask-form`). `styles.css` still carries
~500 lines of dead CSS for deleted U-Swap pages — harmless, but don't assume a class is in use just
because it is defined.

Dependencies are **pinned** in `package.json` (U-Swap had them all on `latest`, which broke builds
on untouched code). Keep them pinned.

## How work happens here
Every change starts with a design doc, then a plan, then implementation — never straight to code.
Both live under `docs/superpowers/`: `specs/` for approved designs, `plans/` for the task-by-task
breakdown. Read the newest spec before touching related code; the reasoning behind a decision, and
the alternatives that were rejected and why, are there rather than in the commit log.

Retrieval decisions are settled by measurement, not argument. The eval set exists so that "this
should work better" can be checked instead of believed.

## Conventions
- Identifiers in English; code comments and user-visible strings in Spanish.
- **Local-only repo — no remote, nothing gets pushed to GitHub.** The original U-Swap project, with
  its GitHub remote, lives separately under `Escritorio/Proyectos Universidad/u-swap` and must not
  be touched from here. Do not add a remote.
- Mark deliberate shortcuts with a `repoqa:` comment naming the ceiling and the upgrade path.
