"""Recuperacion: busqueda vectorial, busqueda lexica y su fusion."""
import re

CANDIDATES_PER_RANKER = 30
RRF_K = 60
DOC_WEIGHT = 0.7
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


def fuse(ranked_ids: list[list[int]], paths: dict[int, str]) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion sobre varias listas ordenadas por relevancia.

    Cada documento suma 1/(RRF_K + posicion) por cada lista donde aparece. Se
    usan las *posiciones* y no los puntajes porque la distancia coseno (0 a 2) y
    ts_rank_cd (sin cota superior) viven en escalas incomparables: normalizarlas
    exigiria calibrar, los rankings no.

    DOC_WEIGHT se aplica antes de que el llamador recorte a top_k — penalizar
    una lista ya truncada no cambiaria que documentos sobreviven.
    """
    scores: dict[int, float] = {}
    for ranked in ranked_ids:
        for position, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + position)

    for chunk_id in scores:
        if _is_doc(paths[chunk_id]):
            scores[chunk_id] *= DOC_WEIGHT

    return sorted(scores.items(), key=lambda pair: -pair[1])


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

    print("retrieval OK — tsquery y fusion RRF")


if __name__ == "__main__":
    _self_check()
