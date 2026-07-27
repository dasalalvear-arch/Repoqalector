from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.repo import SearchHit, SearchRequest
from app.services import retrieval

router = APIRouter()


@router.post("", response_model=list[SearchHit])
def search(payload: SearchRequest, db: Session = Depends(get_db)) -> list[SearchHit]:
    """Busqueda semantica pura, sin LLM.

    Existe para poder evaluar la recuperacion por separado de la generacion: si
    los chunks que salen de aqui no contienen la respuesta, ningun modelo la va
    a inventar bien. Es el paso previo a /ask.
    """
    # Un repo mal escrito devolvia lista vacia, indistinguible de "no encontre
    # nada". El 404 lo dice.
    if not retrieval.repo_exists(db, payload.repo):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El repositorio '{payload.repo}' no esta indexado",
        )
    return retrieval.search(db, payload.repo, payload.question, payload.top_k, payload.mode)
