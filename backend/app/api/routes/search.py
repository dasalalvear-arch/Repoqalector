from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.chunk import CodeChunk
from app.schemas.repo import SearchHit, SearchRequest
from app.services.embeddings import embed_one

router = APIRouter()


@router.post("", response_model=list[SearchHit])
def search(payload: SearchRequest, db: Session = Depends(get_db)) -> list[SearchHit]:
    """Busqueda semantica pura, sin LLM.

    Existe para poder evaluar la recuperacion por separado de la generacion: si
    los chunks que salen de aqui no contienen la respuesta, ningun modelo la va
    a inventar bien. Es el paso previo a /ask.
    """
    question_vector = embed_one(payload.question)

    # Coseno porque all-MiniLM-L6-v2 produce vectores normalizados.
    distance = CodeChunk.embedding.cosine_distance(question_vector)
    rows = db.execute(
        select(CodeChunk, distance.label("distance"))
        .filter(CodeChunk.repo == payload.repo)
        .order_by(distance)
        .limit(payload.top_k)
    ).all()

    return [
        SearchHit(
            file_path=chunk.file_path,
            line_start=chunk.line_start,
            line_end=chunk.line_end,
            content=chunk.content,
            distance=round(float(dist), 4),
        )
        for chunk, dist in rows
    ]
