# Diseño: reranking con cross-encoder

**Fecha:** 2026-11-15
**Estado:** aprobado, pendiente de plan de implementación
**Antecede:** `2026-07-27-rrf-reweighting-design.md` (dejó el híbrido en 20% / 66%),
`2026-07-27-ask-endpoint-design.md` (`/ask` consume estos mismos 5 fragmentos)

## Problema

El híbrido con `LEXICAL_WEIGHT = 2.0` acierta 3/15 en acierto@1 y 10/15 (66%) en acierto@5 sobre
`dasalalvear-arch/u-swap`. El objetivo es 80% (12/15). Ninguna ponderación de la fusión lo alcanzó:
las preguntas que fallan traen otro archivo de código como mejor candidato, y RRF solo ve
posiciones, no contenido.

Antes de diseñar se midió dónde queda el archivo esperado dentro del pool completo que arma la
fusión (35 a 51 fragmentos por pregunta), no solo en el top-5:

| Pregunta que falla | Puesto del archivo esperado en el pool |
|---|---|
| dónde se decide si un usuario es admin | 9 |
| cómo se filtra el catálogo por categoría | 31 |
| dónde se configura la conexión a la base de datos | 32 |
| dónde se define la tabla de usuarios | no está en el pool |
| dónde se guardan las imágenes de una publicación | no está en el pool |

**Tres de las cinco fallas son de orden, no de recuperación:** el fragmento correcto ya fue
recuperado y quedó enterrado. Eso es exactamente lo que un reranker puede arreglar. Las otras dos
no las arregla ningún reordenamiento, porque no hay nada que reordenar.

## Objetivo

Subir acierto@5 por encima de 10/15 reordenando el pool que ya existe.

**El techo de este cambio es 13/15 (86%)**, y llegar al 80% exige rescatar 2 de las 3 preguntas de
la tabla. Las dos que no están en el pool quedan fuera de alcance a propósito: ampliar el pool es
otra variable, y medir dos cambios a la vez no dice cuál de los dos funcionó.

Si ningún modelo de la rejilla supera 10/15, la conclusión es que el reranking no aporta en este
caso: `hybrid` sigue siendo el default y el README lo dice. Es un hallazgo válido.

## Enfoque

El híbrido arma el pool como hoy. Un cross-encoder puntúa cada par (pregunta, fragmento) leyendo
ambos textos juntos, y se devuelven los `top_k` con mayor puntaje. La diferencia con el ranker
vectorial es que este último compara dos embeddings calculados por separado; el cross-encoder ve la
pregunta y el código en la misma pasada, a cambio de ser demasiado lento para correr sobre todo el
repo. Por eso va segundo, sobre unas decenas de candidatos.

Se descartaron:

- **El cross-encoder como tercer ranker dentro de RRF.** Conserva las anclas léxicas, pero agrega
  un peso más que calibrar y diluye por posiciones al ranker que se supone más preciso. Si el
  reranker es mejor que la fusión, debe decidir el orden; si no lo es, no debe entrar.
- **Reordenar con el LLM (Gemini).** Gasta la cuota de 20 consultas diarias en cada búsqueda, y
  `/search` dejaría de funcionar sin API key.

## Diseño

### Componentes

**`backend/app/services/rerank.py`** (nuevo). Una función:

```python
def rerank(question: str, chunks: list[CodeChunk]) -> list[tuple[CodeChunk, float]]
```

Devuelve todos los fragmentos ordenados de mayor a menor puntaje. Usa `CrossEncoder` de
`sentence-transformers`, que ya es dependencia del proyecto: **no se agrega ninguna**.

El modelo se carga en la primera llamada, no al importar, igual que el de embeddings: `/repos`, los
otros modos de búsqueda y los `_self_check()` existentes no deben pagar la carga ni la descarga. Se
cachea en el volumen `/models` que ya monta Docker Compose.

El texto que ve el modelo por fragmento es la ruta del archivo, un salto de línea y el contenido.
La ruta (`backend/app/models/user.py`) es señal: varias preguntas del set preguntan *dónde* está
algo.

El modelo trunca cada par a su longitud máxima (512 tokens). Un fragmento más largo se evalúa por
su comienzo. Queda marcado con un comentario `repoqa:`; partir fragmentos largos es otro cambio.

**`backend/app/core/config.py`.** Un setting, `rerank_model`. Mientras se corre la rejilla se
sobreescribe por proceso con la variable de entorno `RERANK_MODEL`; al adoptar un modelo, ese pasa
a ser el valor por defecto.

**`backend/app/services/retrieval.py`.** `search()` gana un cuarto modo, `rerank`: el mismo pool
fusionado que `hybrid`, **sin recortar**, pasa por `rerank()` y recién ahí se corta a `top_k`. El
modo `hybrid` no cambia, y sus números deben quedar idénticos: cualquier movimiento ahí es un bug.

`DOC_WEIGHT` no se aplica al puntaje del cross-encoder. Sigue afectando el orden del pool, pero
como el pool entero se reordena, deja de influir en el resultado de este modo.

`SearchHit.score` en modo `rerank` es el puntaje del cross-encoder. Mayor sigue siendo mejor, como
en los otros tres modos.

### La rejilla, declarada antes de correr

| Modelo | Rol | Tamaño aprox. |
|---|---|---|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | control: solo inglés, el reranker más usado | 90 MB |
| `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | multilingüe chico | 470 MB |
| `BAAI/bge-reranker-v2-m3` | multilingüe grande | 2,3 GB |

Las preguntas están en español y el código en inglés con comentarios en español. El control en
inglés existe para saber si el multilingüe importa o si el modelo se apoya en los identificadores.

**Se reportan los tres, gane quien gane**, junto a la fila del híbrido sin reranking.

### Cómo se mide

`evaluate.py` acepta `rerank` en `VALID_MODES` y, para todos los modos, reporta además la latencia
de `search()` por pregunta: mediana y máxima. Antes de cronometrar hace una búsqueda de
calentamiento, para que la carga del modelo no cuente como latencia de una pregunta.

```bash
docker compose exec -e RERANK_MODEL=<modelo> backend python -m app.services.evaluate eval/uswap.json rerank
```

La latencia extra del reranker es la diferencia contra la mediana de `hybrid` medida en la misma
máquina.

### Regla de decisión, fijada antes de medir

1. Se descarta todo modelo cuya latencia mediana supere **15 segundos** por pregunta, o que no
   cargue en el contenedor (el de 2,3 GB puede no caber en la memoria asignada a Docker). Se
   reporta igual, como descartado y por qué.
2. Entre los que quedan, se adopta el de **mayor acierto@5, solo si supera 10/15**.
3. Empate en acierto@5: gana el de mayor acierto@1. Si persiste, el más rápido.

Acierto@1 no veta: `/ask` recibe los cinco fragmentos y le basta con que uno contenga la respuesta.
Se reporta, y si el ganador baja de 3/15 el README lo dice.

Adoptar y alcanzar el objetivo son cosas distintas: un modelo con 11/15 se adopta y el README dice
que el 80% sigue sin alcanzarse.

### Si se adopta un modelo

- `rerank_model` toma ese valor por defecto, y `/search` y `/ask` pasan a servir el modo `rerank`.
- Se vuelve a medir `/ask`: se borra `backend/eval/uswap.answers.json` (la recuperación cambió, así
  que las respuestas guardadas ya no corresponden) y se corre `evaluate_ask` completo. Son 15
  llamadas a Gemini, dentro de la cuota diaria de 20, más el juez.
- El README reporta las cuatro métricas de `/ask` antes y después.

Si no se adopta ninguno, el modo `rerank` queda disponible como instrumento de medición, igual que
`vector` y `lexical`, y `/ask` no se vuelve a medir.

### Errores

Si el modelo no carga o falla al puntuar, la petición falla con el error a la vista. **No hay
vuelta silenciosa a `hybrid`:** escondería qué configuración se está sirviendo, y la evaluación
mediría una cosa mientras imprime el nombre de otra.

## Verificación

- `python -m app.services.rerank`: con el modelo configurado, un fragmento que responde la pregunta
  queda por encima de uno que no tiene relación. Es la comprobación de que el modelo cargó y de que
  el orden no está invertido (mayor = mejor).
- `python -m app.services.retrieval` sigue pasando sin descargar ningún modelo de reranking.
- `evaluate ... hybrid` sigue dando 3/15 y 10/15.
- `cd frontend && npm run build`, si cambia algún tipo compartido.

## Riesgos que el resultado debe declarar

- **Prosa contra código.** El cross-encoder puede preferir `RESUMEN.md` para preguntas en español,
  igual que el ranker vectorial. Esta rejilla no agrega penalización a documentos: si pasa, es un
  hallazgo y se reporta cuántos primeros puestos ocupó la documentación.
- **Selección sobre el mismo set.** Elegir el mejor de tres modelos con 15 preguntas infla el
  número del ganador. Cada pregunta vale 6,7 puntos; una diferencia de una pregunta entre modelos
  no distingue a uno de otro.
- **Latencia medida en una sola máquina, en CPU.** El número sirve para la regla de decisión, no
  como dato general.

## Qué se registra en el README

La tabla con las cuatro filas (híbrido y los tres modelos): acierto@1, acierto@5, latencia mediana
y máxima. Qué pasó con las tres preguntas rescatables. El veredicto contra la regla de decisión. Y,
si hubo adopción, las métricas de `/ask` antes y después.

## Fuera de alcance

- Ampliar `CANDIDATES_PER_RANKER` para meter al pool las dos preguntas ausentes. Es el siguiente
  paso natural si el reranking funciona, y se mide aparte.
- Penalizar documentación en el puntaje del reranker.
- Partir fragmentos más largos que 512 tokens.
- Afinar (fine-tuning) un modelo, o probar modelos fuera de la rejilla.
- GPU, cuantización o cualquier optimización de latencia.
