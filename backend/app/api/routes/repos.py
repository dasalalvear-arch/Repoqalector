import subprocess

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.chunk import CodeChunk
from app.schemas.repo import IndexRepoRequest, IndexRepoResponse, RepoSummary
from app.services.ingest import InvalidRepoUrl, index_repo

router = APIRouter()


@router.get("", response_model=list[RepoSummary])
def list_repos(db: Session = Depends(get_db)) -> list[RepoSummary]:
    """Repos indexados. Sin tabla propia: se derivan de los chunks."""
    rows = db.execute(
        select(CodeChunk.repo, func.count(CodeChunk.id))
        .group_by(CodeChunk.repo)
        .order_by(CodeChunk.repo)
    ).all()
    return [RepoSummary(repo=repo, chunks=count) for repo, count in rows]


@router.post("", response_model=IndexRepoResponse, status_code=status.HTTP_201_CREATED)
def index(payload: IndexRepoRequest, db: Session = Depends(get_db)) -> IndexRepoResponse:
    """Clona e indexa un repo. Reindexar el mismo reemplaza sus chunks.

    repoqa: sincrono — un repo mediano tarda entre segundos y un par de minutos
    y el request queda esperando. Si molesta, moverlo a BackgroundTasks y
    exponer el estado de indexacion.
    """
    try:
        result = index_repo(db, payload.url)
    except InvalidRepoUrl as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="El clonado tardo demasiado",
        )
    except subprocess.CalledProcessError:
        # stderr de git puede traer la URL completa; no se propaga al cliente.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo clonar el repositorio (revisa que sea publico y exista)",
        )
    return IndexRepoResponse(**result)


@router.delete("/{owner}/{repo}", status_code=status.HTTP_204_NO_CONTENT)
def delete_repo(owner: str, repo: str, db: Session = Depends(get_db)) -> None:
    deleted = db.query(CodeChunk).filter(CodeChunk.repo == f"{owner}/{repo}").delete()
    db.commit()
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo no indexado")
