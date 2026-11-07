"""Sintesis: de fragmentos recuperados a una respuesta con citas verificables.

Las citas se producen por indice: el modelo ve los fragmentos numerados [1]..[n]
y solo puede escribir esos numeros. El mapeo a archivo y lineas lo hacemos aqui
con los datos que ya teniamos, asi que una ruta inventada es imposible por
construccion. Lo que NO se garantiza es que el fragmento citado respalde la
afirmacion: eso lo mide el juez de evaluate_ask.py.
"""
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.repo import SearchHit
from app.services import llm, retrieval


ABSTAIN_MESSAGE = "No encontre la respuesta en los fragmentos recuperados del repositorio."

SYSTEM_PROMPT = f"""Respondes preguntas sobre un repositorio de codigo usando SOLO los fragmentos numerados que se te entregan.

Reglas:
- Cada afirmacion termina con la referencia al fragmento que la respalda, en el formato [n].
- Si una afirmacion sale de varios fragmentos, escribe [1][3], nunca [1, 3].
- No escribas rutas de archivo ni numeros de linea: solo [n].
- Si los fragmentos no contienen la respuesta, responde exactamente "{ABSTAIN_MESSAGE}" sin ninguna referencia. No adivines.
- Responde en espanol, breve y directo."""

# Captura el espacio previo para que borrar una cita invalida no deje "foo ."
CITATION = re.compile(r"(\s?)\[(\d+)\]")


class MissingApiKey(Exception):
    """GEMINI_API_KEY no esta configurada."""


@dataclass
class AskResult:
    answer: str
    found: bool
    sources: list[SearchHit]  # solo los citados, en orden de aparicion
    retrieved: list[SearchHit]  # todo lo que se le entrego al modelo
    invalid_citations: int


def format_fragments(hits: list[SearchHit]) -> str:
    """Fragmentos numerados desde 1, con su ruta. Lo usan el modelo y el juez."""
    return "\n\n".join(
        f"[{i}] {hit.file_path}:{hit.line_start}-{hit.line_end}\n```\n{hit.content}\n```"
        for i, hit in enumerate(hits, start=1)
    )


def parse_citations(text: str, n: int) -> tuple[str, list[int], int]:
    """Extrae las citas [k] validas (1..n) y renumera el texto para mostrarlo.

    Devuelve (texto, indices base 0 en orden de aparicion, citas invalidas).
    Las invalidas se borran del texto y se cuentan: ese contador es la senal
    directa de alucinacion de citas.
    """
    order: list[int] = []
    invalid = 0

    def renumber(match: re.Match[str]) -> str:
        nonlocal invalid
        k = int(match.group(2))
        if not 1 <= k <= n:
            invalid += 1
            return ""
        if k not in order:
            order.append(k)
        return f"{match.group(1)}[{order.index(k) + 1}]"

    clean = CITATION.sub(renumber, text)
    return clean, [k - 1 for k in order], invalid


def ask(db: Session, repo: str, question: str, top_k: int = 5) -> AskResult:
    hits = retrieval.search(db, repo, question, top_k, "hybrid")
    # Cero fragmentos: no se paga una llamada para preguntar sobre nada.
    if not hits:
        return AskResult(ABSTAIN_MESSAGE, False, [], [], 0)
    # Se chequea al atender la peticion, no al importar: un crash aqui dejaria
    # caidos tambien /search y /repos.
    if not settings.gemini_api_key:
        raise MissingApiKey("GEMINI_API_KEY no esta configurada")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Fragmentos:\n\n{format_fragments(hits)}\n\nPregunta: {question}"},
    ]
    raw = llm.chat(settings.gemini_base_url, settings.gemini_api_key, settings.gemini_model, messages)
    text, indices, invalid = parse_citations(raw, len(hits))
    sources = [hits[i] for i in indices]
    return AskResult(text.strip(), bool(sources), sources, hits, invalid)


def _self_check() -> None:
    # Dos citas validas: fuentes 1 y 3, en ese orden, renumeradas a [1] y [2]
    # para que el numero del texto coincida con la posicion en `sources`.
    text, order, invalid = parse_citations("valida en [1] y guarda en [3].", 5)
    assert order == [0, 2], order
    assert text == "valida en [1] y guarda en [2].", text
    assert invalid == 0

    # Un indice repetido no duplica la fuente.
    text, order, _ = parse_citations("a [2] b [2]", 5)
    assert order == [1], order
    assert text == "a [1] b [1]", text

    # Fuera de rango: se descarta, se cuenta y desaparece del texto mostrado.
    text, order, invalid = parse_citations("existe [1] y no existe [7].", 3)
    assert order == [0], order
    assert invalid == 1, invalid
    assert "[7]" not in text and text == "existe [1] y no existe.", text

    # El cero tampoco es un indice valido: los fragmentos empiezan en 1.
    assert parse_citations("x [0]", 3)[2] == 1

    # Sin citas = abstencion. No hace falta un campo que el modelo rellene.
    text, order, invalid = parse_citations(ABSTAIN_MESSAGE, 5)
    assert order == [] and invalid == 0 and text == ABSTAIN_MESSAGE

    # El orden sigue la aparicion en el texto, no el ranking de recuperacion.
    _, order, _ = parse_citations("primero [4], despues [1]", 5)
    assert order == [3, 0], order

    print("synthesis OK — parseo de citas")


if __name__ == "__main__":
    _self_check()
