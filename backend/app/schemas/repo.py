from typing import Literal

from pydantic import BaseModel, Field

SearchMode = Literal["vector", "lexical", "hybrid"]


class IndexRepoRequest(BaseModel):
    url: str = Field(description="URL https de un repositorio publico de GitHub")


class IndexRepoResponse(BaseModel):
    repo: str
    chunks: int
    files: int


class RepoSummary(BaseModel):
    repo: str
    chunks: int


class SearchRequest(BaseModel):
    repo: str
    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    mode: SearchMode = "hybrid"


class SearchHit(BaseModel):
    file_path: str
    line_start: int
    line_end: int
    content: str
    # Mayor es mejor, en los tres modos. No es una distancia: el puntaje de RRF
    # no tiene unidad, y en modo vectorial se reporta 1 - distancia_coseno para
    # que la direccion sea la misma y las comparaciones no se inviertan.
    score: float
