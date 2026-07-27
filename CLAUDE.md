# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

U-Swap: a circular-economy marketplace for UTEM university students. Students register with an
`@utem.cl` email, publish items, request exchanges (matches), and chat per-match to coordinate
in-person handoffs. No payments. Spanish-facing UI, English code (see Conventions).

Monorepo: `backend/` (FastAPI) + `frontend/` (React/Vite). PostgreSQL via Docker Compose.

`RESUMEN.md` (Spanish) is the long-form project doc — data model, security notes, known
limitations. Read it when you need more depth than this file gives.

There is **no file storage or upload endpoint**: item images are base64 `data:` URLs stored inline
in `item_images.image_url` (TEXT). Big images therefore bloat JSON payloads and DB rows.

## Commands

Run everything (from repo root):
```bash
docker compose up --build      # db + backend:8000 + frontend:5173, API docs at :8000/docs
docker compose down            # stop; add -v to also wipe the Postgres volume (fresh DB)
docker compose logs backend    # also: frontend, db
```

Backend only:
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env         # then set JWT_SECRET_KEY (>=32 chars) or the app won't start
uvicorn app.main:app --reload
```

Frontend only:
```bash
cd frontend
npm install
npm run dev                    # Vite dev server, host 0.0.0.0
npm run build                  # tsc -b && vite build — this is the de-facto "lint/typecheck" gate
```

Demo data (2 students + 7 items, idempotent; both students log in with `demo1234`):
```bash
docker compose exec backend python -m app.services.seed_demo
```

There is **no test suite and no linter configured**. `npm run build` (which runs `tsc -b`) is the
only automated check; run it before committing frontend changes. Note `frontend/package.json` pins
every dependency to `latest`, so a fresh `npm install` can pull breaking majors — a build that
suddenly fails on untouched code is usually that, not your change.

## Architecture

### Backend (`backend/app/`)
Standard FastAPI layered layout. Each domain (auth, users, items, categories, matches, chat, admin)
has a parallel file across four folders:
- `models/` — SQLAlchemy ORM (tables: users, categories, items, item_images, matches, messages)
- `schemas/` — Pydantic request/response shapes
- `api/routes/` — endpoints, mounted in `main.py` under their prefix
- `services/` — startup logic: `seed.py` (admin + categories), `schema.py` (column patches),
  `seed_demo.py` (manual-testing data, run by hand — not on startup)

`core/` holds cross-cutting infra: `config.py` (pydantic-settings, reads `.env`), `database.py`
(engine + `get_db` session dependency), `security.py` (bcrypt + JWT helpers), `limiter.py` (slowapi).

**Startup sequence in `main.py`** runs at import time, before the app object exists:
`Base.metadata.create_all()` creates missing tables, then `ensure_runtime_schema(engine)` patches in
columns added after the fact (role, moderation_status, is_reported), then `create_admin()` +
`ensure_default_categories()` seed data. There are **no migrations** — `create_all` never alters
existing tables, so `services/schema.py::ensure_runtime_schema()` is the hand-rolled stand-in: add a
new column to an existing table by extending that function (it's idempotent). A column that lives
only in the model, with no `ensure_runtime_schema` entry, won't appear on an existing DB unless you
drop the volume (`docker compose down -v`).

**Known model/DB gaps:**
- `items.is_reported` is created by `ensure_runtime_schema` but has **no `Mapped` column in
  `models/item.py`**. Accessing it in Python requires raw SQL or adding the mapped column first.
- Enum label case is inconsistent between the two schema paths. SQLAlchemy's `Enum()` persists the
  Python member **name**, so `ItemModerationStatus` (`pending`/`approved`/`hidden`) creates a
  lowercase-label Postgres type via `create_all`, while `schema.py` declares that same type with
  uppercase labels and an `APPROVED` default. On a fresh DB `create_all` wins and the `DO` block
  no-ops; on a legacy DB missing the column the uppercase path can produce a type whose labels the
  ORM will never match. `UserRole` is safe (names and values both uppercase). If you add an enum
  column, make member names match what `schema.py` writes.

**Docker Compose** reads `env_file: ./backend/.env.example` for the backend service — not `backend/.env`.
Changes to `backend/.env` have no effect in Docker; edit `.env.example` or add an `environment:`
override in `docker-compose.yml` instead.

**Auth flow:** JWT bearer tokens, `sub` = user email. `api/dependencies.py` provides
`get_current_user` (decodes token, loads user) and `get_current_admin` (403 unless `role == ADMIN`).
Use these as route dependencies for protected/admin endpoints. Registration is hard-locked to
`@utem.cl` (`auth.py::validate_utem_email`) and always assigns `UserRole.STUDENT`; admins only come
from the `.env` seed (`ADMIN_EMAIL`/`ADMIN_PASSWORD`), never from the API. Login/register are rate
limited via `@limiter.limit(...)`.

The API serves JSON only — `SecurityHeadersMiddleware` in `main.py` sets a locked-down CSP and
`X-Frame-Options: DENY`; don't expect to serve HTML from here.

### Frontend (`frontend/src/`)
React Router SPA. All routing and role gating lives in `routes/App.tsx`. Pages: Auth, Catalog,
Publish, Matches, MyPublications, Admin. `PublishPage` is dual-purpose — `/publish` creates,
`/publish/:id` edits the same form. Catalog is the only public route; everything else redirects to
`/auth`, and `/admin` bounces students back to `/`.

`services/api.ts` is the single source of truth: a configured Axios instance plus **all** shared TS
types (User, Item, Match, etc. — mirror the backend Pydantic schemas, update both together). A
request interceptor attaches the bearer token from `localStorage["uswap.token"]`; a response
interceptor catches 401-with-active-session, clears the token, and fires a `uswap:unauthorized`
window event. The Axios base URL is read from `VITE_API_URL` at build time (Docker Compose sets it
to `http://localhost:8000`; override via `environment:` in compose or a `.env` file for other
deployments).

`hooks/useAuth.ts` is the auth state machine: reads the token, calls `/auth/me` to hydrate the user,
listens for `uswap:unauthorized` to force-logout, and `login()` returns the user's role so
`routes/App.tsx` can redirect students vs. admins. Auth state lives in this hook (no global store).

### Contract coupling
A change to any model usually ripples through three places — keep them in sync:
`models/<x>.py` → `schemas/<x>.py` → the matching type in `frontend/src/services/api.ts`.

## Conventions
- Code, identifiers, and comments in English; user-visible strings may be Spanish.
- **Local-only repo — no remote, and nothing gets pushed to GitHub.** This is a fresh working copy
  being repurposed; the original U-Swap project (with its GitHub remote) lives separately under
  `Escritorio/Proyectos Universidad/u-swap` and must not be touched from here. Do not add a remote.
- Never commit `.env` (only `.env.example`). `JWT_SECRET_KEY` has no default and must be >=32 chars.
