# Diseño: recuperación híbrida léxica + vectorial

**Fecha:** 2026-07-27
**Estado:** aprobado, pendiente de plan de implementación
**Alcance:** solo recuperación. `/ask` (síntesis con LLM) es un spec aparte.

## Problema

La recuperación semántica actual acierta **0% @1 y 13% @5** contra un set de 15 preguntas
con respuesta conocida sobre el repo `dasalalvear-arch/u-swap` (150 chunks, 57 archivos).

El diagnóstico está cerrado y descarta las causas fáciles:

- **No es un bug de ingesta.** Los 15 archivos esperados están indexados. `utem.cl` aparece
  literalmente en `auth.py:16`, dentro de un chunk indexado.
- **No es el troceo.** La mejor variante de troceo probada (ruta como prefijo, excluyendo
  markdown) llegó a 40% @5. Mejora al margen, no resuelve.
- **No es el idioma del modelo por sí solo.** `paraphrase-multilingual-MiniLM-L12-v2` dio el
  mismo 13% @5 que el modelo solo-inglés.
- **No es la falta de un modelo de código.** `jina-embeddings-v2-base-code` dio 5/15 @5.

La causa es que un bi-encoder de propósito general empareja mal preguntas en lenguaje natural
contra código crudo, y la documentación en prosa española gana el ranking por defecto porque
se parece más a la pregunta que el código al que la pregunta se refiere.

Una medición previa de búsqueda léxica dio 0/15, pero **ese resultado es inválido**:
`plainto_tsquery` une los términos con `AND`, exigiendo que el fragmento contuviera los tres
a la vez. No es evidencia en contra de la vía léxica.

## Objetivo

**acierto@5 ≥ 80%.** Se elige `@5` sobre `@1` porque es la métrica que predice si `/ask`
funcionará: el LLM recibirá 5 fragmentos y basta con que uno contenga la respuesta.

## Restricciones

- Indexado **local y rápido**: sin llamadas a APIs externas, sin claves, sin costo por uso.
  Esto excluye la generación de resúmenes por chunk con un LLM, que es la técnica más efectiva
  conocida para este problema pero convierte el indexado de segundos en minutos.
- La documentación se mantiene indexada. Borrarla subiría la métrica de inmediato, pero deja
  sin buena respuesta a "¿de qué trata este repo?", que es una pregunta central de la demo.

## Enfoque: dos fases, con medición entre ellas

### Fase A — híbrido léxico + vectorial

Dos búsquedas independientes, fusionadas por ranking.

```
pregunta
  ├── vectorial → 30 candidatos (pgvector, distancia coseno)
  ├── léxica    → 30 candidatos (ts_rank_cd sobre tsvector)
  └── fusión RRF + DOC_WEIGHT → top_k
```

Ataca el modo de fallo observado. Las preguntas que fallaron contienen anclas exactas
(`utem.cl`, `bcrypt`, `JWT`) presentes literalmente en el código: la mitad léxica las
encuentra sin esfuerzo, la vectorial aporta el parafraseo cuando no hay palabras compartidas.

### Fase B — reranking con cross-encoder local (condicional)

**Solo si la fase A no alcanza el 80%.** Recuperar 30 candidatos y reordenarlos con un
cross-encoder, que lee pregunta y fragmento juntos en vez de comparar vectores calculados por
separado. Sigue siendo local y gratis (~90MB, cientos de ms por consulta en CPU).

Su límite: solo reordena lo que ya llegó. Con 150 chunks, 30 candidatos son el 20% del corpus
y la cobertura alcanza; en un repo grande esa suposición se cae.

El escalonamiento no es solo pereza: cada fase produce un número, y "el híbrido subió de 13% a
X, el reranking de X a Y" es evidencia de ingeniería, no una afirmación.

## Diseño

### Modelo de datos

Una columna generada en `code_chunks`, más un índice GIN:

```sql
search_vector tsvector GENERATED ALWAYS AS (
    to_tsvector('spanish', file_path || ' ' || content)
) STORED
```

- **Generada, no calculada en la aplicación:** Postgres la mantiene en cada `INSERT`/`UPDATE`.
  No puede desincronizarse de `content`, y `ingest.py` no cambia.
- **Incluye `file_path`:** los nombres de archivo son señal fuerte. Una pregunta sobre
  autenticación debe favorecer `routes/auth.py` aunque el cuerpo no repita la palabra.
- **Configuración `'spanish'`:** elimina las palabras vacías del español (casi toda la pregunta)
  y preserva los identificadores. Verificado:
  `plainto_tsquery('spanish', 'donde se valida que el correo sea @utem.cl')`
  → `'val' & 'corre' & 'utem.cl'`.

**Consecuencia operativa:** el proyecto no tiene migraciones y `create_all` no agrega columnas
a tablas existentes. Aplicar el cambio exige `docker compose down -v` y reindexar (~16s por repo).

### Nuevo módulo: `services/retrieval.py`

La lógica de búsqueda se extrae de la ruta a un servicio:

```python
def search(db, repo, question, top_k, mode) -> list[SearchHit]
```

`mode` ∈ `{"vector", "lexical", "hybrid"}`, con `"hybrid"` por defecto. La ruta `/search` queda
como envoltorio delgado que solo traduce HTTP y traduce el repo inexistente a `404`; el servicio
en sí devuelve lista vacía y no conoce códigos de estado. La evaluación llama a esta misma función.

Reutiliza el `SearchHit` de `schemas/repo.py` en vez de definir un tipo propio: es un objeto de
datos plano y duplicarlo solo crearía dos definiciones que mantener en sincronía.

Contiene además dos funciones puras, verificables sin base de datos ni modelos:

- `build_tsquery(question) -> str` — extrae términos con `[\w.]+` y los une con `|`. El patrón
  restringido cumple doble función: preserva `utem.cl` y descarta por construcción los
  caracteres con significado sintáctico en `tsquery`. Va como parámetro, nunca concatenado.
- `fuse(vector_hits, lexical_hits) -> list[Hit]` — Reciprocal Rank Fusion.

### Fusión: RRF

Cada documento suma `1 / (RRF_K + posición)` por cada lista donde aparece, con `RRF_K = 60`
(valor estándar). Un fragmento 2º en léxica y 8º en vectorial gana sobre uno que es 1º en una
sola lista.

RRF usa **posiciones, no puntajes**: la distancia coseno (0–2) y `ts_rank_cd` (sin cota) viven
en escalas incomparables y normalizarlas exigiría calibración. Los rankings no tienen ese problema.

La fusión ocurre **en Python, no en SQL**. Un CTE equivalente serían ~25 líneas de SQL difíciles
de depurar; en Python es una función pura sobre dos listas ordenadas, legible y verificable de
forma aislada. Son dos consultas simples en vez de una compleja, ambas sobre índices.

### Prioridad del código

`DOC_WEIGHT = 0.7` multiplica el puntaje fusionado de los archivos `.md`/`.rst`. No los elimina:
la documentación puede seguir ganando cuando es claramente la mejor respuesta.

Se aplica **antes** de recortar a `top_k`, no después: penalizar una lista ya truncada no cambiaría
qué documentos sobreviven, que es justamente el efecto buscado.

**Este número es una perilla de calibración, no una constante derivada.** Se anota como tal y el
set de evaluación decide si moverlo. Empezar en 0.7 y medir es más honesto que inventar una
justificación teórica.

### Constantes nombradas

| Constante | Valor inicial | Origen |
|---|---|---|
| `CANDIDATES_PER_RANKER` | 30 | 20% del corpus de prueba |
| `RRF_K` | 60 | valor estándar de la literatura |
| `DOC_WEIGHT` | 0.7 | perilla de calibración, la ajusta la evaluación |

### Cambio de contrato en la respuesta

`SearchHit.distance` deja de tener sentido: el puntaje fusionado de RRF no es una distancia, y
además invierte el orden (en distancia menor es mejor; en RRF mayor es mejor). Se renombra a
`score`, **mayor es mejor**.

Esto rompe el frontend, que hoy muestra `dist {hit.distance}`. `services/api.ts` y `AskPage.tsx`
se actualizan en el mismo cambio — el proyecto ya tiene la convención de mover juntos el schema
Pydantic y su tipo TypeScript.

En modo `"vector"` el `score` se reporta como `1 - distancia_coseno` para que la dirección sea
consistente entre los tres modos y las comparaciones de la evaluación no se inviertan.

### Arnés de evaluación

**`expect` pasa de string a lista.** Acierta si aparece cualquiera de los archivos aceptables:

```json
{ "question": "donde se configura la conexion a la base de datos",
  "expect": ["core/database.py", "core/config.py"] }
```

Varias preguntas tienen más de una respuesta legítima; con un solo archivo esperado el medidor
subestima por construcción y el 80% podría ser inalcanzable por diseño del set, no por calidad
de la recuperación.

**La evaluación mide el código real.** Hoy `evaluate.py` reimplementa el ranking con numpy; dos
implementaciones que pueden divergir en silencio, y si divergen el número medido no es el que
el usuario experimenta. Pasa a llamar a `retrieval.search()`.

**Sacrificio aceptado:** se pierde la comparación de modelos de embeddings sin reindexar, que
dependía de la implementación paralela. Comparar modelos vuelve a costar un reindexado (~16s).
No se justifica mantener dos rankings sincronizados para ahorrar eso.

**`mode` permite medir cada mitad por separado:** vectorial sola (el 13% conocido), léxica sola,
e híbrida. Convierte el resultado en evidencia del aporte de cada pieza.

## Manejo de errores

| Caso | Comportamiento |
|---|---|
| Pregunta sin términos utilizables (solo puntuación) | La mitad léxica devuelve vacío; la fusión degrada a solo-vectorial. Camino válido, no error. |
| Repo inexistente o mal escrito | `404`. Hoy devuelve lista vacía, indistinguible de "no encontré nada". |
| Pregunta vacía | Ya cubierto por `Field(min_length=1)` en el schema. |

## Verificación

Se suman dos self-checks a los dos existentes (`chunker`, `ingest`). Sin framework, estilo
`assert` ejecutable con `python -m`.

**`fuse()`** — sin base de datos ni modelos:
- un documento presente en ambas listas gana a uno que domina una sola
- un documento en una sola lista sobrevive (no se pierde por no estar en ambas)
- `DOC_WEIGHT` hunde un `.md` que empataba con código
- una lista vacía no rompe la fusión

**`build_tsquery()`**:
- `@utem.cl` sobrevive como término
- una pregunta de pura puntuación devuelve vacío sin lanzar excepción

**Integración:** la corrida del set de evaluación recorre el camino real completo.

## Criterio de término de la fase A

Correr la evaluación en los tres modos. Si el híbrido alcanza **80% @5**, la fase A cierra y el
siguiente trabajo es `/ask`. Si no, ese número es la línea base contra la que se justifica la
fase B.

## Fuera de alcance

- `/ask` con síntesis por LLM. Mezclarlo aquí volvería a tapar la medición de recuperación con
  la generación, que es precisamente el error que este trabajo corrige.
- Troceo sintáctico con tree-sitter. Medido de forma aproximada: aporta al margen (40% @5 en la
  mejor variante barata). Se reconsidera si la fase B tampoco alcanza.
- Índice ANN (hnsw/ivfflat) sobre los embeddings. Con repos de este tamaño el escaneo secuencial
  responde en milisegundos.
