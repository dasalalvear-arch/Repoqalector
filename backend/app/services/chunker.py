"""Recorrido de un repo clonado y troceado de sus archivos de codigo.

El troceo es por ventanas de lineas con solapamiento. No entiende sintaxis: no
sabe donde empieza ni termina una funcion. A cambio funciona igual en cualquier
lenguaje y no depende de un parser por cada uno.

repoqa: ventana fija en vez de troceo por funcion/clase. El techo es que un
chunk puede partir una funcion por la mitad; el solapamiento amortigua pero no
lo elimina. Si la evaluacion muestra respuestas cortadas, el upgrade es
tree-sitter (multi-lenguaje) o `ast` de stdlib (solo Python).
"""
from pathlib import Path
from typing import Iterator, NamedTuple

CHUNK_LINES = 50
OVERLAP_LINES = 10

# Allowlist en vez de blocklist: es mas corta y falla del lado seguro (un
# formato nuevo se ignora en vez de colarse como basura binaria en el indice).
CODE_EXTENSIONS = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb", ".php",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".kt", ".swift", ".scala", ".sh",
    ".sql", ".html", ".css", ".scss", ".vue", ".svelte",
    ".md", ".rst", ".toml", ".yaml", ".yml",
})

SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".next", ".nuxt", "target", "vendor", ".idea", ".vscode", "migrations",
})

# Los lockfiles son enormes y no contienen logica: solo ensucian el indice.
SKIP_FILES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Cargo.lock", "composer.lock", "Gemfile.lock",
})

MAX_FILE_BYTES = 500_000


class Chunk(NamedTuple):
    file_path: str
    line_start: int
    line_end: int
    content: str


def iter_source_files(root: Path) -> Iterator[Path]:
    """Archivos de codigo del repo, saltando dependencias, binarios y lockfiles."""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name in SKIP_FILES or path.suffix.lower() not in CODE_EXTENSIONS:
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        yield path


def chunk_lines(lines: list[str], file_path: str) -> Iterator[Chunk]:
    """Ventanas de CHUNK_LINES con OVERLAP_LINES de solapamiento.

    Las lineas se numeran desde 1 porque line_start/line_end se le muestran al
    usuario como cita y tienen que coincidir con lo que ve en su editor.
    """
    if not lines:
        return

    step = CHUNK_LINES - OVERLAP_LINES
    start = 0
    while start < len(lines):
        window = lines[start:start + CHUNK_LINES]
        content = "".join(window).strip()
        if content:
            yield Chunk(
                file_path=file_path,
                line_start=start + 1,
                line_end=start + len(window),
                content=content,
            )
        # Si la ventana ya llego al final, cortamos: sin esto la ultima ventana
        # parcial se re-emitiria en bucle cuando el archivo es mas corto que step.
        if start + CHUNK_LINES >= len(lines):
            break
        start += step


def chunk_repo(root: Path) -> Iterator[Chunk]:
    """Todos los chunks del repo clonado en `root`."""
    for path in iter_source_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except (UnicodeDecodeError, OSError):
            # Binario disfrazado de texto o archivo ilegible: se salta.
            continue
        yield from chunk_lines(lines, path.relative_to(root).as_posix())


def _self_check() -> None:
    """Verifica lo unico con logica real aqui: los limites de la ventana."""
    lines = [f"line {i}\n" for i in range(1, 121)]
    chunks = list(chunk_lines(lines, "x.py"))

    # Cobertura total: la primera linea y la ultima tienen que estar indexadas.
    assert chunks[0].line_start == 1, chunks[0]
    assert chunks[-1].line_end == 120, chunks[-1]

    # Solapamiento real entre ventanas consecutivas.
    assert chunks[1].line_start == 41, chunks[1]
    assert chunks[0].line_end == 50, chunks[0]

    # Sin huecos: cada ventana empieza antes de que termine la anterior.
    for previous, current in zip(chunks, chunks[1:]):
        assert current.line_start <= previous.line_end, (previous, current)

    # Archivo mas corto que la ventana: un solo chunk, sin bucle infinito.
    short = list(chunk_lines([f"l{i}\n" for i in range(5)], "s.py"))
    assert len(short) == 1, short
    assert short[0].line_start == 1 and short[0].line_end == 5, short[0]

    # Archivo vacio y archivo solo con espacios: nada que indexar.
    assert list(chunk_lines([], "e.py")) == []
    assert list(chunk_lines(["\n", "   \n"], "w.py")) == []

    print(f"chunker OK — {len(chunks)} chunks para 120 lineas")


if __name__ == "__main__":
    _self_check()
