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
| `POST /search` — recuperación híbrida (vectorial + léxica, fusión RRF ponderada) | ✅ (ver [Resultados de recuperación](#resultados-de-recuperación) — 20% acierto@1, 66% acierto@5; no alcanza el objetivo del 80%) |
| `POST /ask` — síntesis con LLM sobre los chunks, citas por índice | ✅ (ver [Resultados de `/ask`](#resultados-de-ask)) |
| Frontend: selector de repo + respuesta con citas numeradas | ✅ |
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
| **Híbrido (RRF, peso léxico 2.0)** | **20%** | **66%** |

La búsqueda vectorial sola falla porque un modelo de propósito general empareja mal
preguntas en lenguaje natural contra código crudo, y la documentación en prosa gana
el ranking por parecerse más a la pregunta. La mitad léxica aporta las anclas exactas
(`utem.cl`, `bcrypt`, `JWT`) que aparecen literalmente en el código.

El híbrido le gana al léxico en ambas métricas, pero **solo después de reponderar la
fusión**. Con pesos iguales quedaba en 33%/53%, por debajo del léxico en acierto@5.

### Reponderación de la fusión

Con pesos iguales, un fragmento que solo aparece en la lista vectorial en posición 1
puntúa `1/61 = 0.0164` y le gana a uno que solo aparece en la léxica en posición 5
(`1/65 = 0.0154`). Como el ranker vectorial acierta 0% en acierto@1 por sí solo, su
cabeza es ruido desplazando aciertos reales. Por eso se le dio más peso al léxico.

El vectorial pesa `1.0` fijo; solo varía el peso del léxico. Los tres valores se
fijaron antes de medir, y se reportan los tres.

| Peso léxico | acierto@1 | acierto@5 |
|---|---|---|
| 1.0 (control) | 33% | 53% |
| 1.5 | 26% | 53% |
| **2.0** | **20%** | **66%** |

Ninguno cumple el criterio que se había fijado (acierto@5 > 60% **y** acierto@1 ≥ 33%),
porque ese umbral de acierto@1 estaba anclado al del híbrido sin reponderar. Ese criterio
estaba mal planteado: lo que importa es si la fusión le gana al léxico solo, y con peso
`2.0` le gana en las dos métricas (20% contra 13%, 66% contra 60%). Servir léxico sería
servir una configuración peor en ambos números.

La elección real está entre `1.0` y `2.0`, y ahí sí hay un intercambio: `1.0` acierta más
veces al primer intento, `2.0` cubre más en el top-5. Se eligió `2.0` porque acierto@5 es
la métrica que predice si `/ask` va a funcionar — el LLM recibe cinco fragmentos y le basta
con que uno contenga la respuesta.

Dos advertencias sobre este resultado. **`2.0` es el extremo superior de la rejilla**, así
que el óptimo real podría estar más allá y no se exploró. Y **subir el peso léxico acerca
la fusión al léxico puro**: que el vectorial aporte poco es parte de lo que dice este
número, no algo que la fusión haya resuelto.

Sigue sin alcanzarse el objetivo del 80% en acierto@5 (66%, 10/15). De las 5 preguntas que
fallan, la mayoría trae otro archivo de código como mejor candidato equivocado — confusión
código-contra-código que ninguna ponderación arregla. `DOC_WEIGHT` se dejó en `0.7` porque
la documentación no es lo que ocupa los primeros puestos; moverlo habría sido ajustar
contra ruido. El siguiente paso natural es el reranking con cross-encoder.

Reproducir: `docker compose exec backend python -m app.services.evaluate eval/uswap.json <modo>`

## Resultados de `/ask`

Mismo repo y mismas 15 preguntas. Responde `gemini-3.5-flash-lite` sobre los 5 fragmentos del
modo híbrido. Lo que el modelo *debía* hacer sale del propio set: si el archivo esperado entró en
lo recuperado, debía responder; si no, debía abstenerse.

| Métrica | Resultado |
|---|---|
| Respondió cuando debía | 9/10 (90%) |
| Se abstuvo cuando debía | 2/5 (40%) |
| Citas inválidas (índice fuera de rango) | 1 |
| Fundamentadas según el juez (`openai/gpt-oss-120b`, vía Groq) | 11/12 (91%) |

Las dos primeras son un intercambio: un prompt más miedoso sube una y hunde la otra, así que se
leen juntas.

**El 40% de abstención es menos grave de lo que parece.** En las 3 preguntas donde respondió sin
tener el archivo esperado, citó `RESUMEN.md` — la documentación en prosa del repo, que sí describe
lo preguntado. El juez dio por fundamentadas 2 de esas 3: la respuesta estaba respaldada por un
fragmento real, solo que no por el archivo que el set considera correcto. Es el mismo problema de
recuperación de arriba (la prosa le gana al código), visto desde la respuesta.

**La cita inválida no llegó al usuario.** Como las citas se producen por índice, una referencia a
un fragmento que no existe se descarta al parsear y se cuenta. Ocurrió en una respuesta, y es la
misma que el juez marcó como no fundamentada: quedó una afirmación sin respaldo. El objetivo era 0;
se reporta 1 en vez de ajustar el prompt contra 15 preguntas hasta que desaparezca.

El juez es de otra familia de modelos que el que responde, para que no se evalúe a sí mismo. Sigue
siendo un LLM: el 91% es una señal, no una verificación.

Reproducir: `docker compose exec backend python -m app.services.evaluate_ask eval/uswap.json`

Las respuestas y los veredictos quedan guardados en `backend/eval/uswap.answers.json`, así que
volver a correr no gasta cuota. Se regeneran solas si cambia el modelo o el prompt; si cambia la
recuperación, hay que borrar el archivo.

## Uso

```bash
curl -X POST http://localhost:8000/repos -H "Content-Type: application/json" -d "{\"url\":\"https://github.com/owner/repo\"}"
```

```bash
curl -X POST http://localhost:8000/search -H "Content-Type: application/json" -d "{\"repo\":\"owner/repo\",\"question\":\"donde se valida el login\"}"
```

```bash
curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d "{\"repo\":\"owner/repo\",\"question\":\"donde se valida el login\"}"
```

`/ask` necesita una key de Gemini; `/repos` y `/search` funcionan sin ella. Las keys van en un
`.env` en la raíz del repo (está en `.gitignore`), nunca en `backend/.env.example`:

```
GEMINI_API_KEY=...   # obligatoria para /ask
JUDGE_API_KEY=...    # opcional, solo para el juez de la evaluación
```

Reindexar el mismo repo reemplaza sus chunks. La primera búsqueda tras levantar el contenedor tarda
unos segundos: es la descarga del modelo de embeddings (~90MB, queda cacheado en un volumen).

## Verificaciones

No hay suite de tests. Lo que sí hay:

```bash
cd frontend && npm run build                                  # tsc -b, el gate de tipos
docker compose exec backend python -m app.services.chunker    # límites de las ventanas
docker compose exec backend python -m app.services.ingest     # validación de URLs
docker compose exec backend python -m app.services.retrieval  # tsquery y fusión RRF
docker compose exec backend python -m app.services.synthesis  # parseo de citas
docker compose exec backend python -m app.services.evaluate_ask --check   # métricas y veredicto del juez
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
