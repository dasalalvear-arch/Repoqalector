import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.repo import AskRequest, AskResponse
from app.services import llm, retrieval, synthesis

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=AskResponse)
def ask(payload: AskRequest, db: Session = Depends(get_db)) -> AskResponse:
    """Respuesta en lenguaje natural con citas a archivo y lineas."""
    if not retrieval.repo_exists(db, payload.repo):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El repositorio '{payload.repo}' no esta indexado",
        )
    try:
        result = synthesis.ask(db, payload.repo, payload.question, payload.top_k)
    except synthesis.MissingApiKey:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Falta configurar GEMINI_API_KEY en el backend",
        )
    except llm.LLMError as error:
        # El error crudo del proveedor queda en el log, no viaja al cliente.
        logger.error("Fallo la llamada a Gemini: %s", error)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El modelo no respondio. Intenta de nuevo.",
        )
    if result.invalid_citations:
        logger.warning("Citas fuera de rango descartadas: %d", result.invalid_citations)

    sources = result.sources if result.found else result.retrieved
    return AskResponse(answer=result.answer, found=result.found, sources=sources)
