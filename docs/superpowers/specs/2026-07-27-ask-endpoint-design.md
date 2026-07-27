# Diseño: `POST /ask` — síntesis con LLM y citas verificables

**Fecha:** 2026-07-27
**Estado:** aprobado, pendiente de plan de implementación
**Antecede:** `2026-07-27-hybrid-retrieval-design.md`, `2026-07-27-rrf-reweighting-design.md`

## Problema

La recuperación funciona y está medida: híbrido con peso léxico `2.0` da 20% acierto@1 y 66%
acierto@5 sobre las 15 preguntas de `backend/eval/uswap.json`. Hoy `/search` devuelve fragmentos
crudos; falta la mitad que convierte eso en un producto: una respuesta en lenguaje natural que cite
de dónde salió.

El riesgo central no es que el modelo responda mal. Es que responda bien **con una cita inventada**.
El proyecto existe para dar respuestas que puedas verificar; una cita que apunta a un archivo que el
modelo nunca vio rompe exactamente esa promesa, y lo hace de forma invisible para el usuario.

Y hay un dato que condiciona todo el diseño: con 66% de acierto@5, **una de cada tres preguntas llega
al modelo sin la respuesta en el contexto.**

## Decisiones tomadas

1. **Ante contexto insuficiente, el modelo se abstiene.** Responde que no encontró la respuesta en el
   repositorio, y se muestran igual los fragmentos por si sirven. Una respuesta inventada con una
   cita bien formateada es peor que ninguna respuesta.
2. **Las citas se producen por índice, no por texto libre.** Ver más abajo.
3. **La evaluación es automática y sin juez:** abstención correcta más integridad de citas.

## Diseño

### Flujo

```
POST /ask {repo, question}
  → retrieval.search(repo, question, top_k, mode="hybrid")   ← reutilizado sin cambios
  → prompt con los fragmentos numerados [1]..[n]
  → Gemini
  → extraer indices [n], mapear a las citas reales
  → {answer, found, sources}
```

### Contrato

```python
class AskRequest(BaseModel):
    repo: str
    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class AskResponse(BaseModel):
    answer: str
    found: bool                 # False = se abstuvo
    sources: list[SearchHit]    # solo los citados, en orden de aparicion
```

`sources` reutiliza `SearchHit` (ruta, líneas, contenido, score) en vez de definir un tipo propio: el
frontend ya sabe renderizarlo y duplicarlo crearía dos definiciones que mantener sincronizadas.

### Citas por índice

Los fragmentos van al prompt numerados, cada uno con su ruta. El modelo escribe prosa marcando de
dónde saca cada afirmación: *"la validación ocurre en `[1]`"*.

**Fabricar una cita se vuelve estructuralmente imposible.** El modelo no escribe rutas ni números de
línea — elige entre `1` y `n`. El mapeo a `file_path`/`line_start`/`line_end` lo hacemos nosotros
con los datos que ya teníamos.

Se descartó que el modelo escriba la ruta en texto (`auth.py:16-19`): es lo más natural de pedir y
por eso es la trampa — puede inventar una ruta plausible o acertar el archivo y desplazar las
líneas, y validarlo contra lo enviado es hacer lo mismo que el índice con un parser más frágil.

Se descartó también la salida estructurada en JSON con las citas en un campo aparte: el parseo sería
más robusto, pero se pierde **qué parte** de la respuesta viene de cuál fuente. Para un producto cuyo
punto es verificar afirmación por afirmación, las citas ancladas al texto valen más que un bloque al
final.

**Límite conocido:** este diseño garantiza que la cita apunta a un fragmento que el modelo
efectivamente recibió. **No** garantiza que ese fragmento respalde lo que la respuesta afirma. Eso no
lo resuelve ningún esquema de citas — solo leerlas, que es justamente lo que el producto permite.

### Parseo

`re.findall(r"\[(\d+)\]", answer)`. Se conservan los índices dentro de rango, sin repetir, en orden
de aparición.

- `found` es `bool(indices_validos)`. **La abstención no necesita un campo que el modelo deba
  rellenar bien: es la ausencia de citas.**
- Los índices fuera de rango se borran del texto mostrado **y se cuentan**. Ese contador es la señal
  directa de alucinación de citas y hace el sistema auditable en vez de confiable por fe.

### Modelo de Gemini

El identificador del modelo es un valor de configuración (`GEMINI_MODEL` en `core/config.py`), no una
constante escrita en el código. Los nombres de modelos cambian y el que esté disponible depende de la
key; se confirma contra Google AI Studio al implementar en vez de fijar uno de memoria.

La key llega por `GEMINI_API_KEY`, inyectada desde un `.env` en la raíz que git ignora. **Nunca en
`backend/.env.example`**, que sí está versionado y es lo que `docker-compose.yml` lee vía `env_file`.

## Manejo de errores

| Caso | Comportamiento |
|---|---|
| La recuperación no devuelve fragmentos | Se abstiene **sin llamar a Gemini**. No tiene sentido pagar una llamada para preguntar sobre cero fragmentos |
| Falta `GEMINI_API_KEY` | `503` con mensaje claro, al atender la petición. No un crash al importar el módulo, que dejaría caído también `/search` y `/repos` |
| Gemini falla, expira o devuelve error | `502`. El error crudo del proveedor no se propaga al cliente |
| Repo no indexado | `404`, igual que `/search` |
| Pregunta vacía | Cubierto por `Field(min_length=1)` |

## Evaluación

**Arnés aparte: `backend/app/services/evaluate_ask.py`.** No se extiende `evaluate.py` porque mide
otra cosa y, sobre todo, porque necesita la API key: mezclarlos rompería la evaluación de
recuperación para quien no tenga credenciales configuradas. Dos instrumentos, dos dependencias.

Lo que lo hace barato: el set actual ya dice, por pregunta, si la recuperación acertó. De ahí sale
qué debería hacer el modelo.

| Métrica | Qué mide |
|---|---|
| Respondió cuando debía | De las preguntas donde la recuperación acertó en top-k, ¿en cuántas respondió en vez de abstenerse? |
| Se abstuvo cuando debía | De las preguntas donde la recuperación falló, ¿en cuántas se calló en vez de inventar? |
| Citas inválidas | Índices fuera de rango emitidos, sumados sobre las 15 preguntas |

Las dos primeras son un **intercambio, no dos metas independientes**: un prompt más miedoso sube la
segunda y hunde la primera. Se reportan juntas siempre, porque mirar una sola lleva a ajustar el
prompt en la dirección equivocada.

La tercera **debería ser cero**. Si no lo es, hay un bug de prompt o de parseo, no una cuestión de
calidad del modelo.

**Limitación declarada:** esto no mide si la respuesta es correcta en contenido. Mide si el modelo se
comporta como debe dado lo que recibió. Una respuesta que cita el archivo correcto y describe mal el
código pasaría las tres métricas. Medir corrección exige ojos humanos o un LLM juez, y se decidió no
introducir un juez para no agregar una variable de calidad que no controlamos.

## Frontend

`AskPage` pasa de `/search` a `/ask`:

- El texto de la respuesta arriba, los chips de cita debajo, y el código de cada fragmento citado.
- Cuando se abstiene, muestra el mensaje **y de todas formas los fragmentos recuperados**: que no
  haya respuesta sintetizada no significa que el código encontrado sea inútil.

`services/api.ts` y el componente se actualizan juntos, como ya se hizo con `distance` → `score`. El
endpoint deja de devolver `SearchHit[]` directo y pasa a devolver `{answer, found, sources}`.

## Verificación

Siguiendo la convención del repo (sin framework de tests, `_self_check()` con `assert` corrido por
`python -m`):

**Parseo de citas**, que es la lógica pura y la que sostiene la promesa del producto:
- `[1]` y `[3]` en el texto producen las fuentes 1 y 3, en ese orden
- un índice repetido no duplica la fuente
- un índice fuera de rango se descarta, se cuenta, y desaparece del texto mostrado
- una respuesta sin ninguna cita da `found = False`
- el orden de las fuentes sigue el de aparición en el texto, no el del ranking

`/search`, `/repos` y los self-checks existentes deben seguir pasando sin API key configurada.

## Fuera de alcance

- Historial de conversación. Cada pregunta es independiente; el frontend ya acumula turnos para
  mostrarlos, pero no se envían como contexto.
- Streaming de la respuesta.
- LLM como juez de corrección.
- Reranking con cross-encoder para cerrar la brecha de 66% a 80% en acierto@5. Sigue pendiente y es
  independiente de este trabajo.
