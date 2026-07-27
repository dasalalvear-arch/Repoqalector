# Diseño: reponderar la fusión RRF

**Fecha:** 2026-07-27
**Estado:** aprobado, pendiente de plan de implementación
**Antecede:** `2026-07-27-hybrid-retrieval-design.md` (fase A)

## Problema

La fase A dejó estas mediciones sobre `dasalalvear-arch/u-swap` (150 fragmentos, 15 preguntas):

| Modo | acierto@1 | acierto@5 |
|---|---|---|
| Vectorial | 0% | 26% |
| Léxico | 13% | **60%** |
| Híbrido (RRF, pesos iguales) | **33%** | 53% |

**La fusión perdió contra su propia mitad léxica en acierto@5.** Combinar salió peor que no combinar
en la métrica que gatilla la fase B.

La causa sale de las constantes, no de una hipótesis. RRF asigna `1/(RRF_K + posición)` con
`RRF_K = 60` y cada ranker aporta 30 candidatos. Entonces:

- un fragmento que solo aparece en la lista vectorial, en posición 1, puntúa `1/61 = 0.01639`
- un fragmento que solo aparece en la lista léxica, en posición 5, puntúa `1/65 = 0.01538`

El ruido vectorial en cabeza le gana a aciertos léxicos reales. Y el ranker vectorial tiene **0% de
acierto@1 por sí solo**, así que sus primeros puestos son precisamente ruido. Con pesos iguales, un
ranker que nunca acierta primero desplaza del top-5 a uno que sí.

## Objetivo

Que el híbrido supere al léxico en **ambas** métricas: **acierto@5 > 60%** manteniendo
**acierto@1 ≥ 33%**.

Si ningún peso de la rejilla lo logra, la conclusión es que la fusión no aporta en este caso:
`/search` pasa a modo léxico y el README lo dice. Ese es un hallazgo válido, no un fracaso — es más
honesto que conservar maquinaria que empeora el resultado.

## Diseño

### El cambio

`fuse()` acepta un peso por ranker:

```python
def fuse(ranked_ids, paths, weights=None):
    weights = weights or [1.0] * len(ranked_ids)
    for ranked, weight in zip(ranked_ids, weights):
        for position, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (RRF_K + position)
```

`search()` pasa `[1.0, LEXICAL_WEIGHT]`, en el mismo orden en que ya construye `ranked_ids`
(vectorial primero, léxico segundo).

**El vectorial queda anclado en 1.0 y solo se mueve el léxico.** Con dos pesos libres existirían
infinitas combinaciones equivalentes —`(2, 3)` ordena igual que `(4, 6)`— y ninguna forma de comparar
corridas entre sí. Un grado de libertad, un número que reportar.

La aritmética que justifica esto: con `LEXICAL_WEIGHT = 1.5`, el fragmento léxico en posición 5 pasa
de `0.01538` a `1.5/65 = 0.02308`, por encima del `0.01639` del vectorial en posición 1. El
mecanismo del problema queda invertido.

### Cómo se corre la rejilla

`LEXICAL_WEIGHT` es una constante de módulo en `backend/app/services/retrieval.py`. Se edita, se
mide, se repite.

Se descartaron una variable de entorno y un argumento nuevo en `search()`: ambos dejan plomería
permanente para un experimento que se corre una vez. `DOC_WEIGHT` ya vive como constante simple y
esto queda consistente. Si algún día hay que calibrar por repositorio, ahí el knob se gana su lugar.

### La rejilla, declarada antes de correr

| Valor | Rol |
|---|---|
| `1.0` | control — reproduce el 33%/53% actual |
| `1.5` | primer valor con efecto según la aritmética de arriba |
| `2.0` | límite superior de la rejilla |

**Se reportan los tres, gane quien gane.** Tres valores fijos y anunciados de antemano dejan poco
espacio para pescar un resultado favorable: con 15 preguntas cada una vale 6.7 puntos, y probar
valores hasta que uno luzca bien produciría un número ajustado al set en vez de evidencia.

Se descartó partir el set en ajuste y validación: con 7 preguntas de validación cada una valdría 14
puntos, y ese número sería tan ruidoso que daría falsa confianza en vez de menos.

## Verificación

Dos asserts nuevos en el `_self_check()` que ya existe en `retrieval.py`:

- **Guarda de regresión:** `fuse()` sin el argumento `weights` produce exactamente el mismo
  resultado que antes del cambio. Si esta aserción cae, la corrida está midiendo dos cambios a la
  vez y los números no son comparables con la fase A.
- **El peso tiene efecto:** un peso de `2.0` en la segunda lista invierte un orden que con pesos
  iguales no se invertía. Sin esto, una implementación que ignore `weights` pasaría desapercibida y
  la rejilla entera devolvería el mismo número tres veces sin que nadie lo note.

Los modos `vector` y `lexical` no pasan por `fuse()`, así que sus números deben quedar idénticos a
los de la fase A. Cualquier movimiento ahí es un bug, no un resultado.

## Qué se registra en el README

Las tres filas de la rejilla, más el veredicto contra el criterio de aceptación.

**Si el ganador es el peso más alto de la rejilla**, el README debe decir explícitamente que eso
significa que el ranker vectorial aporta poco — no que la fusión triunfó. Un peso léxico creciente
hace converger la fusión hacia el léxico puro; leer eso como éxito de la fusión sería engañarse.

## Fuera de alcance

- Recortar `CANDIDATES_PER_RANKER` solo para el vectorial. Truncar de 30 a 10 elimina las posiciones
  11-30, que son sus candidatos más débiles; los que hacen daño son los de posición 1-3 y sobreviven
  al recorte. No toca el mecanismo del problema.
- Subir `RRF_K` para aplanar la curva. No corrige la asimetría entre rankers, solo reduce la
  influencia de la posición en ambos por igual.
- Filtrar candidatos vectoriales por umbral de distancia absoluta. Introduce una constante que
  necesita calibración por modelo de embeddings, y el modelo puede cambiar.
- La fase B (reranking con cross-encoder). Sigue pendiente y depende del resultado de esta rejilla.
- `/ask` con síntesis por LLM. Spec aparte.
