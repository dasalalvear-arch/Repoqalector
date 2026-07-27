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
| `POST /search` — recuperación híbrida (vectorial + léxica, fusión RRF) | ✅ (ver [Resultados de recuperación](#resultados-de-recuperación) — no alcanza el 80% de acierto@5, y el híbrido queda por debajo del léxico solo en esa métrica) |
| Frontend: selector de repo + búsqueda con citas | ✅ |
| `POST /ask` — síntesis con LLM sobre los chunks | ⬜ |
| Set de evaluación (15 preguntas con respuesta conocida, varias con más de un archivo válido) | ✅ |

**Por qué `/search` antes que `/ask`:** si la recuperación trae los fragmentos equivocados, ningún
LLM lo arregla — solo lo disfraza. Tener la búsqueda expuesta por separado permite medir la calidad
de la recuperación sin que la generación la tape.

## Resultados de recuperación

Medido sobre `dasalalvear-arch/u-swap` (150 fragmentos, 57 archivos) con las 15
preguntas de `backend/eval/uswap.json`, cuya respuesta correcta se verificó a mano.

| Modo | acierto@1 | acierto@5 |
|---|---|---|
| Vectorial (embeddings) | 0% | 26% |
| Léxico (Postgres full-text) | 13% | 60% |
| **Híbrido (RRF)** | **33%** | **53%** |

El dato que hay que decir sin rodeos: en acierto@5 el híbrido (53%) queda **por debajo**
del léxico solo (60%) — la fusión no superó a su propia mitad léxica en la métrica que
más importa. Donde el híbrido sí gana con claridad es en acierto@1 (33% contra 13% del
léxico). Combinar ambos rankers era el punto de construir RRF; en acierto@5, combinar
salió peor que no combinar.

La búsqueda vectorial sola falla porque un modelo de propósito general empareja mal
preguntas en lenguaje natural contra código crudo, y la documentación en prosa gana
el ranking por parecerse más a la pregunta. La mitad léxica aporta las anclas exactas
(`utem.cl`, `bcrypt`, `JWT`) que aparecen literalmente en el código.

El híbrido no alcanza el objetivo del 80% en acierto@5 (53%, 8/15): de las 7 preguntas
que fallan, 6 traen otro archivo de código como mejor candidato equivocado (confusión
código-contra-código que ninguna fusión arregla) y solo 1 trae un `.md`. Como la
documentación no es lo que ocupa los primeros puestos, `DOC_WEIGHT` se dejó en `0.7`
— subirle el peso de penalización no habría movido el número, solo habría ajustado
contra ruido.

Esta medición no alcanza para elegir el siguiente paso, pero sí señala uno. El patrón —
la fusión ayuda en acierto@1 donde el léxico es débil, y perjudica en acierto@5 donde el
léxico ya es fuerte — es la firma típica de un ranker ruidoso (vectorial, 0% de acierto@1
por sí solo) diluyendo a uno bueno dentro de una fusión a peso igual: hoy `fuse()` en
`retrieval.py` reparte 50/50 entre vectorial y léxico, sin ponderar ninguno de los dos.
Subirle el peso a la mitad léxica en la fusión (y revisar `CANDIDATES_PER_RANKER` de paso)
es una hipótesis más barata que meter un reranker con cross-encoder, y esta misma medición
apunta hacia ahí. No decide si funcionará: falta correrla y medirla antes de comprometerse
a una fase de reranking.

Reproducir: `docker compose exec backend python -m app.services.evaluate eval/uswap.json <modo>`

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
