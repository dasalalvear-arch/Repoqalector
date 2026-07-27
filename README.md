# RepoQA

Asistente de preguntas y respuestas sobre un repositorio de código. Indexas un repo, preguntas en
lenguaje natural, y la respuesta viene **citando el archivo y el rango de líneas** de donde salió —
para que puedas verificarla en vez de confiar en ella.

> `RepoQA` es un nombre provisorio.

## Stack

- **Backend:** FastAPI, SQLAlchemy, PostgreSQL + [pgvector](https://github.com/pgvector/pgvector)
- **Frontend:** React + TypeScript + Vite
- **Infra local:** Docker Compose

## Arranque

```bash
docker compose up --build
```

- Frontend: http://localhost:5173
- API docs: http://localhost:8000/docs

Para borrar también la base de datos: `docker compose down -v`.

Manual, sin Docker:

```bash
cd backend && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt && copy .env.example .env && uvicorn app.main:app --reload
```

`npm run build` (`tsc -b && vite build`) es la única verificación automatizada del proyecto — no hay
suite de tests ni linter configurados.

## Estado

| Pieza | Estado |
|---|---|
| Esqueleto FastAPI + pgvector + tabla `code_chunks` | ✅ |
| Frontend de preguntas con citas | ✅ UI lista, esperando el backend |
| `POST /repos` — clonar, trocear e indexar | ⬜ |
| `GET /repos` — repos indexados | ⬜ |
| `POST /ask` — búsqueda semántica + LLM | ⬜ |
| Set de evaluación | ⬜ |

## Modelo de datos

Una sola tabla, `code_chunks`:

| Columna | Para qué |
|---|---|
| `repo` | agrupa y filtra por repositorio |
| `file_path`, `line_start`, `line_end` | la cita que se le muestra al usuario |
| `content` | el texto del fragmento; va al prompt como contexto |
| `embedding` | `vector(384)`, la búsqueda por similitud |

No hay tabla `repos`: `SELECT DISTINCT repo` alcanza mientras el selector sea una lista.

## Decisiones

- **Sin autenticación** en el MVP: es una herramienta local de un solo usuario. Reintroducir login
  cuesta poco (el patrón JWT del proyecto anterior es reutilizable) y no vale la pena antes de tiempo.
- **Sin migraciones:** el proyecto arranca en limpio, `create_all` alcanza.
- **384 dimensiones** porque el modelo de embeddings previsto es `all-MiniLM-L6-v2`. Cambiar de
  modelo cambia ese número y obliga a reindexar todo.
