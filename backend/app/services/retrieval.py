"""Recuperacion: busqueda vectorial, busqueda lexica y su fusion."""
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chunk import TEXT_SEARCH_CONFIG, CodeChunk
from app.schemas.repo import SearchHit
from app.services import rerank
from app.services.embeddings import embed_one

CANDIDATES_PER_RANKER = 30
RRF_K = 60
DOC_WEIGHT = 0.7
# Peso del ranker lexico dentro de RRF; el vectorial queda fijo en 1.0. Con
# pesos iguales un fragmento solo-vectorial en posicion 1 (1/61) le gana a uno
# solo-lexico en posicion 5 (1/65), y el vectorial acierta 0% en @1 por si
# solo: su cabeza es ruido desplazando aciertos reales.
# repoqa: constante fija, no configurable. Se calibra editandola y corriendo
# la evaluacion. Si algun dia hay que calibrar por repositorio, ahi se
# justifica moverla a configuracion.
LEXICAL_WEIGHT = 2.0
DOC_EXTENSIONS = (".md", ".rst")


def build_tsquery(question: str) -> str:
    """Convierte la pregunta en una tsquery con OR entre terminos.

    El patron `[\\w.]+` cumple doble funcion: preserva identificadores como
    `utem.cl` y descarta por construccion los caracteres con significado
    sintactico en tsquery (`&`, `|`, `!`, `:`, parentesis). Los puntos sueltos
    se recortan para que "..." no genere un termino vacio.

    Devuelve "" cuando no queda ningun termino; quien llame debe tratarlo como
    "no hay busqueda lexica", no como error.
    """
    terms = [token.strip(".") for token in re.findall(r"[\w.]+", question.lower())]
    return " | ".join(term for term in terms if term)


def _is_doc(path: str) -> bool:
    return path.lower().endswith(DOC_EXTENSIONS)


def fuse(
    ranked_ids: list[list[int]],
    paths: dict[int, str],
    weights: list[float] | None = None,
) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion sobre varias listas ordenadas por relevancia.

    Cada documento suma `peso / (RRF_K + posicion)` por cada lista donde
    aparece. Se usan las *posiciones* y no los puntajes porque la distancia
    coseno (0 a 2) y ts_rank_cd (sin cota superior) viven en escalas
    incomparables: normalizarlas exigiria calibrar, los rankings no.

    `weights` da un peso por lista, en el mismo orden que `ranked_ids`. Sin el,
    todas pesan 1.0 y el resultado es identico al de la fusion sin pesos.

    DOC_WEIGHT se aplica antes de que el llamador recorte a top_k — penalizar
    una lista ya truncada no cambiaria que documentos sobreviven.
    """
    if weights is None:
        weights = [1.0] * len(ranked_ids)

    scores: dict[int, float] = {}
    for ranked, weight in zip(ranked_ids, weights):
        for position, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (RRF_K + position)

    for chunk_id in scores:
        if _is_doc(paths[chunk_id]):
            scores[chunk_id] *= DOC_WEIGHT

    return sorted(scores.items(), key=lambda pair: -pair[1])


def repo_exists(db: Session, repo: str) -> bool:
    return db.query(CodeChunk.id).filter(CodeChunk.repo == repo).first() is not None


def _vector_candidates(db: Session, repo: str, question: str) -> list[tuple[CodeChunk, float]]:
    """Candidatos por similitud de embeddings. Devuelve (chunk, score) con mayor = mejor."""
    distance = CodeChunk.embedding.cosine_distance(embed_one(question))
    rows = db.execute(
        select(CodeChunk, distance.label("distance"))
        .filter(CodeChunk.repo == repo)
        .order_by(distance)
        .limit(CANDIDATES_PER_RANKER)
    ).all()
    return [(chunk, 1.0 - float(value)) for chunk, value in rows]


def _lexical_candidates(db: Session, repo: str, question: str) -> list[tuple[CodeChunk, float]]:
    """Candidatos por texto completo. Lista vacia si la pregunta no deja terminos."""
    terms = build_tsquery(question)
    if not terms:
        return []

    tsquery = func.to_tsquery(TEXT_SEARCH_CONFIG, terms)
    rank = func.ts_rank_cd(CodeChunk.search_vector, tsquery)
    rows = db.execute(
        select(CodeChunk, rank.label("rank"))
        .filter(CodeChunk.repo == repo, CodeChunk.search_vector.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(CANDIDATES_PER_RANKER)
    ).all()
    return [(chunk, float(value)) for chunk, value in rows]


def _to_hits(scored: list[tuple[CodeChunk, float]], top_k: int) -> list[SearchHit]:
    return [
        SearchHit(
            file_path=chunk.file_path,
            line_start=chunk.line_start,
            line_end=chunk.line_end,
            content=chunk.content,
            score=round(score, 4),
        )
        for chunk, score in scored[:top_k]
    ]


def search(
    db: Session,
    repo: str,
    question: str,
    top_k: int = 5,
    mode: str = "hybrid",
) -> list[SearchHit]:
    """Busqueda semantica, lexica, fusionada o fusionada y reordenada.

    `mode` existe para poder medir cada etapa por separado en la evaluacion:
    "vector" y "lexical" son las dos mitades, "hybrid" su fusion, y "rerank" la
    fusion reordenada por un cross-encoder.
    """
    if mode == "vector":
        return _to_hits(_vector_candidates(db, repo, question), top_k)
    if mode == "lexical":
        return _to_hits(_lexical_candidates(db, repo, question), top_k)

    vector = _vector_candidates(db, repo, question)
    lexical = _lexical_candidates(db, repo, question)

    by_id = {chunk.id: chunk for chunk, _ in vector + lexical}
    paths = {chunk_id: chunk.file_path for chunk_id, chunk in by_id.items()}
    ranked_ids = [
        [chunk.id for chunk, _ in vector],
        [chunk.id for chunk, _ in lexical],
    ]
    # El orden coincide con ranked_ids: vectorial primero, lexico segundo.
    fused = fuse(ranked_ids, paths, [1.0, LEXICAL_WEIGHT])
    if mode == "rerank":
        # El pool entero, sin recortar: cortar antes dejaria fuera justo los
        # fragmentos enterrados que el reranker viene a rescatar. DOC_WEIGHT ya
        # no influye aqui, porque el orden lo decide el cross-encoder.
        pool = [by_id[chunk_id] for chunk_id, _ in fused]
        return _to_hits(rerank.rerank(question, pool), top_k)
    return _to_hits([(by_id[chunk_id], score) for chunk_id, score in fused], top_k)


def _self_check() -> None:
    # --- build_tsquery ---------------------------------------------------
    # Los identificadores con punto sobreviven enteros: son el ancla exacta
    # que la busqueda vectorial no encuentra.
    assert build_tsquery("donde se valida el correo @utem.cl") == (
        "donde | se | valida | el | correo | utem.cl"
    ), build_tsquery("donde se valida el correo @utem.cl")

    # OR, no AND: exigir todos los terminos fue el error de la medicion previa.
    assert "&" not in build_tsquery("hash de contrasenas")

    # Una pregunta sin terminos utilizables no puede reventar: la mitad lexica
    # queda vacia y la fusion degrada a solo-vectorial.
    assert build_tsquery("...") == "", build_tsquery("...")
    assert build_tsquery("  ") == ""

    # --- fuse -------------------------------------------------------------
    code = {1: "a.py", 2: "b.py", 3: "c.py", 4: "d.py", 5: "e.py"}

    # Estar en ambas listas gana sobre dominar una sola.
    fused = fuse([[1, 2, 3], [2, 4, 5]], code)
    assert fused[0][0] == 2, fused

    # Un documento presente en una sola lista igual sobrevive.
    assert 4 in [chunk_id for chunk_id, _ in fused], fused
    assert len(fused) == 5, fused

    # Una lista vacia no rompe la fusion.
    only_one = fuse([[], [7]], {7: "x.py"})
    assert only_one == [(7, 1.0 / (RRF_K + 1))], only_one

    # DOC_WEIGHT hunde un .md que iba por delante de un archivo de codigo.
    mixed = fuse([[10, 20]], {10: "README.md", 20: "app.py"})
    assert mixed[0][0] == 20, mixed

    # Sin la penalizacion, el .md iba primero: confirma que el orden cambio por
    # DOC_WEIGHT y no porque el ranking ya lo pusiera segundo.
    unpenalized = fuse([[10, 20]], {10: "a.py", 20: "app.py"})
    assert unpenalized[0][0] == 10, unpenalized

    # --- pesos por ranker --------------------------------------------------
    # Guarda de regresion: sin `weights`, el resultado tiene que ser identico
    # al de antes del cambio. Si esto cae, la rejilla de la fase siguiente
    # estaria midiendo dos cambios a la vez y sus numeros no serian
    # comparables con los de la fase A.
    assert fuse([[1, 2]], {1: "a.py", 2: "b.py"}) == [
        (1, 1.0 / (RRF_K + 1)),
        (2, 1.0 / (RRF_K + 2)),
    ], fuse([[1, 2]], {1: "a.py", 2: "b.py"})

    # El peso tiene que cambiar el orden de verdad. Sin esta comprobacion, una
    # implementacion que ignore `weights` pasaria desapercibida y la rejilla
    # devolveria el mismo numero tres veces sin que nadie lo note.
    #
    # 10 sale primero en la lista vectorial; 20 sale segundo en la lexica.
    # Con pesos iguales gana 10 (1/61 > 1/62). Con peso lexico 2.0 gana 20
    # (2/62 > 1/61). Se comparan posiciones relativas y no quien va primero
    # en absoluto, porque 40 empata con 10 y el empate no es lo que se mide.
    weight_paths = {10: "a.py", 20: "b.py", 40: "c.py"}
    equal_order = [chunk_id for chunk_id, _ in fuse([[10], [40, 20]], weight_paths)]
    assert equal_order.index(10) < equal_order.index(20), equal_order

    weighted_order = [
        chunk_id for chunk_id, _ in fuse([[10], [40, 20]], weight_paths, [1.0, 2.0])
    ]
    assert weighted_order.index(20) < weighted_order.index(10), weighted_order

    print("retrieval OK — tsquery y fusion RRF")


if __name__ == "__main__":
    _self_check()
