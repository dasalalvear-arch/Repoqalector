# RepoQA — Asistente RAG para preguntas sobre repositorios de código

Proyecto personal · 2026 · Backend + Frontend + Docker · Repositorio local

## Descripción (2–3 líneas, para el CV)

Asistente que responde preguntas en lenguaje natural sobre un repositorio de GitHub y **cita el archivo y el rango
de líneas** de cada afirmación, para que la respuesta se pueda verificar en vez de creerla. Pipeline RAG completo:
clonado e indexación, recuperación híbrida (vectorial + full-text), síntesis con LLM y evaluación medida.

## Stack

| Capa | Tecnologías |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy 2, Pydantic |
| Base de datos | PostgreSQL + pgvector (búsqueda vectorial) y full-text search nativo (`tsvector`) |
| Embeddings | sentence-transformers, `all-MiniLM-L6-v2` (384 dimensiones) |
| LLM | Gemini (respuestas) y Groq (juez de evaluación) vía endpoints compatibles con OpenAI |
| Frontend | React 18, TypeScript, Vite, Axios |
| Infra | Docker Compose (db + backend + frontend) |
| Proceso | Specs y planes por fase (`docs/superpowers/`), evaluación antes y después de cada cambio |

## Qué hace

1. **Indexa** un repo de GitHub: clona, filtra archivos de código, lo trocea en ventanas de 50 líneas con 10 de
   solape, genera embeddings y los guarda en pgvector junto con `file_path` y `line_start/line_end`.
2. **Busca** con recuperación híbrida: ranking vectorial + ranking léxico (Postgres full-text), fusionados con
   Reciprocal Rank Fusion ponderado.
3. **Responde** (`POST /ask`): arma un prompt con los fragmentos numerados, llama al LLM y mapea los índices
   citados de vuelta a archivo y líneas reales.
4. **Evalúa**: set de 15 preguntas con respuesta verificada a mano y un arnés que mide la recuperación y las
   respuestas.

## Logros

- Diseñé e implementé un pipeline RAG de punta a punta: ingestión, recuperación híbrida, síntesis con LLM,
  API REST y frontend con citas verificables.
- **Recuperación híbrida medida, no supuesta:** sobre 15 preguntas evaluadas, el ranking vectorial solo logró
  0% de acierto@1 y 26% de acierto@5; el léxico solo, 13% / 60%; el híbrido ponderado, **20% / 66%**.
- **Citas anti-alucinación por diseño:** el modelo no escribe rutas ni números de línea, solo elige un índice
  `[n]` entre los fragmentos que recibió; el backend hace el mapeo. Fabricar una cita queda estructuralmente
  imposible, y los índices fuera de rango se descartan y se cuentan como señal de alucinación.
- **Abstención en vez de inventar:** `found = false` es simplemente la ausencia de citas válidas (no depende de
  que el modelo rellene un campo bien). Si la recuperación no trae nada, se responde sin gastar una llamada al LLM.
- **Arnés de evaluación propio** con métricas mecánicas (respondió cuando debía, se abstuvo cuando debía,
  citas inválidas) más un **juez de fundamentación** con un proveedor distinto al generador para evitar
  que un modelo califique a su propia familia.
- Arnés **reanudable**: guarda cada respuesta en disco con una huella del modelo y del prompt, y se invalida
  solo si cambian.
- Columna `search_vector` **generada y persistida** por Postgres: el índice léxico no puede desincronizarse del
  contenido y la ingestión no tiene que tocarlo.
- Manejo de errores explícito: 404 repo no indexado, 503 sin API key (sin tumbar `/search` ni `/repos`),
  502 ante fallo del proveedor sin filtrar el error crudo.
- Validación de URLs de ingestión (solo `github.com`, patrón estricto de ruta) y timeout de clonado.
- Todo con **Docker Compose** en un comando; claves del LLM fuera del repositorio (`.env` ignorado por git,
  inyectado vía `environment:`).

## Problemas que resolví

| Problema | Causa | Solución |
|---|---|---|
| La búsqueda vectorial acertaba 0% en el primer resultado | Un modelo de propósito general empareja mal preguntas en lenguaje natural contra código crudo; la documentación en prosa se parece más a la pregunta y gana el ranking | Añadí una segunda mitad léxica (full-text) que aporta anclas exactas (`bcrypt`, `JWT`, dominios) y fusioné ambos rankings con RRF |
| El híbrido sin ajustar quedaba por debajo del léxico en acierto@5 (33% / 53%) | Con pesos iguales, la cabeza ruidosa del ranker vectorial desplazaba aciertos reales del léxico | Ponderé la fusión; probé tres pesos fijados antes de medir (1.0 / 1.5 / 2.0) y reporté los tres. Con 2.0: 20% / 66% |
| El criterio de aceptación que me había fijado estaba mal planteado | El umbral de acierto@1 estaba anclado al híbrido sin reponderar, no a la pregunta correcta | Lo corregí: lo que importa es si la fusión le gana al léxico solo. Documenté el criterio fallido en vez de esconderlo, y lo registré en el commit |
| Cita inventada con formato correcto | Pedirle al LLM rutas y líneas en texto libre permite rutas plausibles o líneas desplazadas | Citas por índice: el modelo elige un número, el backend resuelve el resto |
| `CREATE TABLE` fallaba con `type "vector" does not exist` | `create_all()` corría antes de crear la extensión | Ejecutar `CREATE EXTENSION IF NOT EXISTS vector` antes de `create_all()` en el arranque |
| El eval podía divergir de lo que ve el usuario | Una reimplementación del ranking en el script mediría otra cosa | El arnés llama al mismo `retrieval.search()` que usa la API |
| `gemini-2.5-flash` dejó de estar disponible para cuentas nuevas (404 aunque aparecía en la lista de modelos) | Modelo retirado por el proveedor | El modelo es configuración (`GEMINI_MODEL`), no constante; cambié a otro y verifiqué con una llamada real |
| Errores 429 durante la evaluación | No era un límite por minuto sino una cuota diaria (20 solicitudes) del plan gratuito; el retry/pausa no lo arreglaba | Leí el cuerpo del error (`LLMError` ahora incluye estado y mensaje del proveedor), presupuesté las llamadas, reduje a un modelo con mejor cuota y volví el arnés reanudable |
| El juez configurado no existía en el proveedor | Nombre de modelo ausente en la lista de Groq | Verifiqué contra la lista real del proveedor y elegí otro modelo de otra familia para evitar auto-evaluación |
| Dependencias en `latest` rompían el build del frontend | Versiones sin fijar en el proyecto origen | Fijé todas las versiones en `package.json` |

## Decisiones de ingeniería que puedo defender en entrevista

- **`/search` antes que `/ask`:** si la recuperación trae los fragmentos equivocados, ningún LLM lo arregla, solo
  lo disfraza. Exponer la búsqueda por separado permite medirla sin que la generación la tape.
- **Medir antes de cambiar:** cada cambio de recuperación se decidió con el set de evaluación, no con intuición.
- **Reportar los resultados negativos:** el objetivo de 80% en acierto@5 **no** se alcanzó (66%, 10/15); queda
  documentado junto con la causa probable (confusión código-contra-código) y el siguiente paso (reranking con
  cross-encoder).
- **Sin sobre-ingeniería deliberada:** sin autenticación (herramienta local), sin migraciones, sin capa de
  abstracción de proveedores con una sola implementación (un cliente HTTP con URL base configurable), sin
  framework de tests (`_self_check()` con `assert` ejecutable por `python -m`).
- **Metodología:** diseño → plan → implementación por fases, con documentos de diseño que registran las
  alternativas descartadas y por qué.

## Limitaciones honestas (conviene tenerlas listas)

- El set de evaluación es pequeño (15 preguntas sobre un solo repo); los porcentajes son indicativos, no estadística.
- 66% de acierto@5 significa que una de cada tres preguntas llega al LLM sin la respuesta en el contexto,
  por eso existe la abstención.
- Las citas por índice garantizan que el fragmento fue recibido por el modelo, **no** que respalde la afirmación;
  de eso se encarga el juez de fundamentación, que no mide corrección factual.
- El frontend ya consume `/ask`, pero faltan por completar la corrida de evaluación de `/ask` y el juez completo.
  No cites métricas de `/ask` hasta tenerlas.

## Versiones listas para pegar

**Una línea**
> RepoQA — Asistente RAG que responde preguntas sobre repos de GitHub citando archivo y líneas. FastAPI, PostgreSQL/pgvector, React/TypeScript, Docker.

**Bullets (formato CV)**
- Desarrollé un asistente RAG (FastAPI, PostgreSQL + pgvector, React/TypeScript, Docker) que responde preguntas sobre repositorios de código citando archivo y rango de líneas verificables.
- Implementé recuperación híbrida (embeddings + full-text de Postgres) con fusión RRF ponderada; la medí sobre un set de 15 preguntas verificadas a mano y pasó de 0% / 26% (solo vectorial) a 20% / 66% de acierto@1 / acierto@5.
- Diseñé citas por índice que impiden estructuralmente que el LLM invente rutas o líneas, con abstención explícita cuando el contexto no alcanza.
- Construí un arnés de evaluación reanudable (métricas mecánicas + juez de fundamentación con un proveedor distinto al generador) y resolví límites de cuota, modelos retirados y errores de proveedor leyendo y documentando las causas reales.
