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
| `POST /repos` — clonar, trocear, embeder e indexar | ✅ |
| `GET /repos` · `DELETE /repos/{owner}/{repo}` | ✅ |
| `POST /search` — recuperación pura, sin LLM | ✅ |
| Frontend: selector de repo + búsqueda con citas | ✅ |
| `POST /ask` — síntesis con LLM sobre los chunks | ⬜ |
| Set de evaluación (10-15 preguntas con respuesta conocida) | ⬜ |

**Por qué `/search` antes que `/ask`:** si la recuperación trae los fragmentos equivocados, ningún
LLM lo arregla — solo lo disfraza. Tener la búsqueda expuesta por separado permite medir la calidad
de la recuperación sin que la generación la tape.

## Uso

```bash
curl -X POST http://localhost:8000/repos -H "Content-Type: application/json" -d "{\"url\":\"https://github.com/owner/repo\"}"
```

```bash
curl -X POST http://localhost:8000/search -H "Content-Type: application/json" -d "{\"repo\":\"owner/repo\",\"question\":\"donde se valida el login\"}"
```

Reindexar el mismo repo reemplaza sus chunks. La primera búsqueda tras levantar el contenedor tarda
unos segundos: es la descarga del modelo de embeddings (~90MB, queda cacheado en un volumen).

## Verificaciones

No hay suite de tests. Lo que sí hay:

```bash
cd frontend && npm run build                                  # tsc -b, el gate de tipos
docker compose exec backend python -m app.services.chunker    # límites de las ventanas
docker compose exec backend python -m app.services.ingest     # validación de URLs
```

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
