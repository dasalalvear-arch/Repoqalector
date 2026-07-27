"""Clonado e indexado de un repositorio publico de GitHub."""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.chunk import CodeChunk
from app.services.chunker import chunk_repo
from app.services.embeddings import embed

CLONE_TIMEOUT_SECONDS = 180
EMBED_BATCH = 128

ALLOWED_HOSTS = frozenset({"github.com", "www.github.com"})
# owner/repo de GitHub: alfanumericos, guiones, guion bajo y punto.
REPO_PATH_PATTERN = re.compile(r"^/[\w.-]+/[\w.-]+?(?:\.git)?/?$")


class InvalidRepoUrl(ValueError):
    """La URL no es un repositorio publico de GitHub sobre https."""


def normalize_repo_url(raw_url: str) -> tuple[str, str]:
    """Valida la URL y devuelve (url_de_clonado, nombre_owner/repo).

    Seguridad: esta URL termina en la linea de comandos de `git clone`. Se
    restringe a https y a github.com a proposito — sin esto, esquemas como
    ext:: o file:// permiten ejecutar comandos arbitrarios o leer el disco del
    contenedor. Ademas se rechaza userinfo (https://user:token@...) para que
    nadie meta credenciales en la URL ni las deje escritas en la BD.
    """
    parsed = urlparse(raw_url.strip())

    if parsed.scheme != "https":
        raise InvalidRepoUrl("Solo se aceptan URLs https://")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise InvalidRepoUrl("Solo se aceptan repositorios de github.com")
    if parsed.username or parsed.password:
        raise InvalidRepoUrl("La URL no puede incluir credenciales")
    if not REPO_PATH_PATTERN.match(parsed.path):
        raise InvalidRepoUrl("La ruta debe tener la forma /owner/repo")

    owner_repo = parsed.path.strip("/").removesuffix(".git")
    return f"https://github.com/{owner_repo}.git", owner_repo


def clone(repo_url: str, destination: Path) -> None:
    """Clona sin historial. Lista de argumentos, nunca shell=True."""
    subprocess.run(
        ["git", "clone", "--depth", "1", "--no-tags", "--", repo_url, str(destination)],
        check=True,
        capture_output=True,
        timeout=CLONE_TIMEOUT_SECONDS,
        # Evita que git pida usuario/clave y se quede colgado con un repo privado.
        env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin"},
    )


def index_repo(db: Session, raw_url: str) -> dict[str, object]:
    """Clona, trocea, embede y guarda. Reindexar reemplaza lo anterior."""
    clone_url, name = normalize_repo_url(raw_url)

    # El clon es temporal: lo que persiste son los chunks, no el checkout.
    workdir = Path(tempfile.mkdtemp(prefix="repoqa-"))
    try:
        clone(clone_url, workdir)
        chunks = list(chunk_repo(workdir))
        if not chunks:
            raise InvalidRepoUrl("No se encontraron archivos de codigo indexables")

        # Borrado + insercion en la misma transaccion: si algo falla a mitad,
        # el indice anterior sigue intacto en vez de quedar a medias.
        db.query(CodeChunk).filter(CodeChunk.repo == name).delete()

        for start in range(0, len(chunks), EMBED_BATCH):
            batch = chunks[start:start + EMBED_BATCH]
            vectors = embed([chunk.content for chunk in batch])
            db.add_all([
                CodeChunk(
                    repo=name,
                    file_path=chunk.file_path,
                    line_start=chunk.line_start,
                    line_end=chunk.line_end,
                    content=chunk.content,
                    embedding=vector,
                )
                for chunk, vector in zip(batch, vectors)
            ])
        db.commit()

        files = len({chunk.file_path for chunk in chunks})
        return {"repo": name, "chunks": len(chunks), "files": files}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _self_check() -> None:
    """Verifica la validacion de URL: es lo que separa `git clone` de un RCE."""
    ok, name = normalize_repo_url("https://github.com/psf/requests")
    assert ok == "https://github.com/psf/requests.git", ok
    assert name == "psf/requests", name

    # Variantes validas que deben normalizar al mismo sitio.
    assert normalize_repo_url("https://github.com/psf/requests.git")[1] == "psf/requests"
    assert normalize_repo_url("  https://github.com/psf/requests/  ")[1] == "psf/requests"

    rejected = [
        "ext::sh -c whoami",                        # ejecucion de comandos via git
        "file:///etc/passwd",                       # lectura del disco local
        "git@github.com:psf/requests.git",          # ssh, no es una URL https
        "http://github.com/psf/requests",           # sin tls
        "https://gitlab.com/psf/requests",          # host no permitido
        "https://evil.com/psf/requests",            # host no permitido
        "https://user:token@github.com/psf/req",    # credenciales en la URL
        "https://github.com/psf",                   # falta el repo
        "https://github.com/a/b/c",                 # ruta con profundidad extra
        "--upload-pack=touch /tmp/pwned",           # flag disfrazado de URL
    ]
    for url in rejected:
        try:
            normalize_repo_url(url)
        except InvalidRepoUrl:
            continue
        raise AssertionError(f"URL peligrosa aceptada: {url!r}")

    print(f"ingest OK — {len(rejected)} URLs peligrosas rechazadas")


if __name__ == "__main__":
    _self_check()
