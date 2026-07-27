from pydantic import BaseModel, Field


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


class SearchHit(BaseModel):
    file_path: str
    line_start: int
    line_end: int
    content: str
    # 0 = identico, 2 = opuesto. Sirve para ver si la busqueda esta trayendo
    # basura sin tener que leer los chunks uno por uno.
    distance: float
