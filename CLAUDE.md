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
POST /repos  → clone → filter files → chunk → embed → INSERT code_chunks
POST /ask    → embed question → pgvector <-> search → build prompt → LLM → {answer, sources}
```

**Current state:** the pipeline is not implemented yet. `backend/app/api/routes/` is empty and
`main.py` mounts no routers — only `/health` exists. The data model and the frontend are ready and
waiting for it. See the status table in `README.md` before assuming an endpoint exists.

### Data model
One table, `code_chunks` (`models/chunk.py`). `file_path` + `line_start`/`line_end` are not
bookkeeping — they are the citation shown to the user, and the whole point of the product. An answer
without a verifiable source is the failure mode this project exists to avoid.

`EMBEDDING_DIM = 384` matches `all-MiniLM-L6-v2`. **Changing the embedding model changes this
number and invalidates every stored vector** — old and new embeddings are not comparable, so a model
switch means reindexing everything.

There is no `repos` table: `SELECT DISTINCT repo` backs the frontend's repo selector.

### Backend (`backend/app/`)
FastAPI layered layout, mostly empty scaffolding right now: `models/`, `schemas/`, `api/routes/`,
`services/`. `core/` holds `config.py` (pydantic-settings, reads `.env`) and `database.py`
(engine + `get_db` session dependency).

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
Because `.env.example` is committed, **never put a real API key in it** — use an `environment:`
override in `docker-compose.yml`, which is where LLM/embedding credentials should go when added.

The db service must stay on `pgvector/pgvector:pg16`; the official `postgres` image lacks the
extension and startup will fail.

### Frontend (`frontend/src/`)
Single page, no router — `routes/App.tsx` renders `AskPage` directly. React Router, the PWA
(manifest + service worker), and the auth hooks were removed; don't reintroduce them for one screen.

`services/api.ts` is the Axios instance plus the shared types (`Answer`, `Source`, `Turn`) that
mirror the backend Pydantic schemas — update both together.

`pages/AskPage.tsx` is adapted from U-Swap's chat UI, which is why the CSS classes are named
`matches-layout` / `match-row` / `message`. The `.sources` / `.source-chip` classes at the bottom of
`styles.css` are the new part: they render the citations under each answer.

Dependencies are **pinned** in `package.json` (U-Swap had them all on `latest`, which broke builds
on untouched code). Keep them pinned.

## Conventions
- Identifiers in English; code comments and user-visible strings in Spanish.
- **Local-only repo — no remote, nothing gets pushed to GitHub.** The original U-Swap project, with
  its GitHub remote, lives separately under `Escritorio/Proyectos Universidad/u-swap` and must not
  be touched from here. Do not add a remote.
- Mark deliberate shortcuts with a `repoqa:` comment naming the ceiling and the upgrade path.
