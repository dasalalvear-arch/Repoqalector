# POST /ask Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn retrieved fragments into a natural-language answer whose citations are chosen by index — so a fabricated path is structurally impossible — and measure it with three mechanical metrics plus an optional groundedness judge.

**Architecture:** `/ask` reuses `retrieval.search()` unchanged, numbers the hits `[1]..[n]` in the prompt, sends them to Gemini, then parses `[n]` markers back to the real `SearchHit`s. One ~30-line stdlib HTTP client talks to any OpenAI-compatible chat endpoint; Gemini exposes one, so the same function serves both the answerer and the judge. The evaluation is a separate harness so the retrieval eval keeps working without credentials.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, PostgreSQL 16 + pgvector, React 18 + TypeScript. **No new dependencies** — HTTP goes through `urllib.request`.

**Spec:** `docs/superpowers/specs/2026-07-27-ask-endpoint-design.md`

## Global Constraints

- **No test framework.** Convention is an assert-based `_self_check()` under `if __name__ == "__main__":`, run with `python -m app.services.<module>`. Do not add pytest.
- Identifiers in English; code comments and user-visible strings in Spanish.
- **No new Python or npm dependencies.** Frontend deps stay pinned.
- **API keys never go in `backend/.env.example`** (it is committed). Keys arrive via `environment:` in `docker-compose.yml` from the gitignored root `.env`. Non-secret settings (model names, base URLs) may go in `.env.example`.
- **`retrieval.py` is not modified.** `/ask` calls `retrieval.search(..., mode="hybrid")` as-is.
- `/search`, `/repos` and every existing `_self_check()` must keep working **with no API key configured**. Nothing may read or require a key at import time.
- Gemini error text is never forwarded to the client (`502` with a generic Spanish message; the real error goes to the server log).
- Deliberate shortcuts carry a `repoqa:` comment naming the ceiling and the upgrade path.
- Local-only repo, no remote, never push.
- Docker must be running. If `docker compose` cannot reach the daemon, stop and report it.
- After changing `docker-compose.yml` or `backend/.env.example`, recreate the backend: `docker compose up -d backend` (a restart does not reread env).

## Decisions this plan adds on top of the spec

1. **Citations are renumbered for display.** If the model cites `[3]` then `[1]`, the shown text reads `[1]` then `[2]` and `sources` is `[hit3, hit1]`. Without this, the number in the text would not match the chip's position in `sources`.
2. **When the model abstains, `sources` carries the retrieved fragments** (none were cited, so "only cited" would be empty). The spec requires the frontend to show them anyway; this avoids a second `/search` call. `found` tells the client which case it is.
3. **Gemini is called through its OpenAI-compatible endpoint** (`https://generativelanguage.googleapis.com/v1beta/openai`). One client function covers Gemini and every judge provider the spec lists.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/core/config.py` | **Modify.** Add `gemini_*` and `judge_*` settings, all defaulting so import never fails. |
| `backend/.env.example` | **Modify.** Non-secret: `GEMINI_MODEL`, `JUDGE_BASE_URL`, `JUDGE_MODEL`. |
| `docker-compose.yml` | **Modify.** Pass `JUDGE_API_KEY` through like `GEMINI_API_KEY`. |
| `backend/app/services/llm.py` | **Create.** `chat()` — one POST to `{base_url}/chat/completions`, returns the text or raises `LLMError`. |
| `backend/app/services/synthesis.py` | **Create.** Prompt building, citation parsing, and `ask()` orchestration. Holds the self-check for the parser, which is the logic the product's promise rests on. |
| `backend/app/schemas/repo.py` | **Modify.** Add `AskRequest`, `AskResponse`. |
| `backend/app/api/routes/ask.py` | **Create.** Thin route: 404 / 503 / 502 mapping over `synthesis.ask()`. |
| `backend/app/main.py` | **Modify.** Register the router. |
| `backend/app/services/evaluate_ask.py` | **Create.** Mechanical metrics + optional judge. |
| `frontend/src/services/api.ts` | **Modify.** `AskResponse` type, `found` on `Turn`. |
| `frontend/src/pages/AskPage.tsx` | **Modify.** Call `/ask`, render answer + numbered chips, or abstention + retrieved fragments. |
| `README.md`, `CLAUDE.md` | **Modify.** Mark `/ask` built, record the eval numbers. |

---

### Task 1: Settings and the LLM client

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Modify: `docker-compose.yml`
- Create: `backend/app/services/llm.py`

**Interfaces:**
- Produces: `settings.gemini_api_key: str`, `settings.gemini_base_url: str`, `settings.gemini_model: str`, `settings.judge_api_key: str`, `settings.judge_base_url: str`, `settings.judge_model: str`
- Produces: `llm.chat(base_url: str, api_key: str, model: str, messages: list[dict[str, str]], timeout: float = 60.0) -> str`, `llm.LLMError(Exception)`

- [ ] **Step 1: Add the settings**

In `backend/app/core/config.py`, add inside `class Settings`, after `clone_dir`:

```python
    # Gemini responde /ask. Se usa su endpoint compatible con el formato de
    # OpenAI para que un solo cliente sirva tambien al juez. La key llega por
    # variable de entorno desde el .env de la raiz; vacia = /ask devuelve 503,
    # pero /search y /repos siguen funcionando.
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_model: str = "gemini-2.5-flash"

    # Juez de fundamentacion: solo lo usa evaluate_ask.py. Cualquier proveedor
    # con endpoint compatible con OpenAI (Groq, Together, OpenRouter).
    judge_api_key: str = ""
    judge_base_url: str = "https://api.groq.com/openai/v1"
    judge_model: str = "llama-3.3-70b-versatile"
```

- [ ] **Step 2: Non-secret values in `.env.example`, key passthrough in compose**

Append to `backend/.env.example`:

```
GEMINI_MODEL=gemini-2.5-flash
JUDGE_BASE_URL=https://api.groq.com/openai/v1
JUDGE_MODEL=llama-3.3-70b-versatile
```

In `docker-compose.yml`, under `backend.environment`, below `GEMINI_API_KEY`:

```yaml
      JUDGE_API_KEY: ${JUDGE_API_KEY:-}
```

- [ ] **Step 3: Write the client**

Create `backend/app/services/llm.py`:

```python
"""Cliente minimo para endpoints de chat compatibles con el formato de OpenAI.

Gemini, Groq, Together y OpenRouter exponen ese formato, asi que cambiar de
proveedor es cambiar base_url, key y modelo — no de codigo.

repoqa: urllib de la stdlib en vez de un SDK. Sin streaming, sin reintentos,
sin pool de conexiones. Si se agrega streaming o hace falta reintentar ante
429, ahi se justifica httpx.
"""
import json
import urllib.error
import urllib.request


class LLMError(Exception):
    """El proveedor fallo, expiro o devolvio algo que no se pudo leer."""


def chat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float = 60.0,
) -> str:
    body = json.dumps({"model": model, "messages": messages, "temperature": 0}).encode()
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Algunos proveedores detras de Cloudflare rechazan el User-Agent
            # por defecto de urllib con un 403.
            "User-Agent": "repoqa/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        return data["choices"][0]["message"]["content"] or ""
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as error:
        raise LLMError(str(error)) from error
```

- [ ] **Step 4: Recreate the backend and confirm the Gemini model id against the key**

```bash
docker compose up -d backend
docker compose exec backend python -c "import json, urllib.request; from app.core.config import settings as s; r = urllib.request.Request(s.gemini_base_url + '/models', headers={'Authorization': 'Bearer ' + s.gemini_api_key}); print(sorted(m['id'] for m in json.load(urllib.request.urlopen(r))['data'] if 'flash' in m['id']))"
```

Expected: a list of model ids containing `flash`. If `models/gemini-2.5-flash` (or `gemini-2.5-flash`) is not there, pick the newest stable `flash` id from the list (not `-preview`, not `-exp`), and use it in both `config.py` and `.env.example`. Then recreate the backend again.

- [ ] **Step 5: One live call through the client**

```bash
docker compose exec backend python -c "from app.core.config import settings as s; from app.services import llm; print(llm.chat(s.gemini_base_url, s.gemini_api_key, s.gemini_model, [{'role': 'user', 'content': 'Responde solo: ok'}]))"
```

Expected: prints `ok` (or something close). An `LLMError` with `404` means the model id is wrong — go back to Step 4. `401`/`403` means the key is wrong or not reaching the container: check `docker compose exec backend printenv GEMINI_API_KEY | wc -c` is greater than 1, **without printing the key**.

- [ ] **Step 6: Confirm nothing regressed without a key**

```bash
docker compose exec -e GEMINI_API_KEY= backend python -m app.services.retrieval
```

Expected: `retrieval OK — tsquery y fusion RRF`

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/config.py backend/.env.example docker-compose.yml backend/app/services/llm.py
git commit -m "feat: settings and stdlib client for OpenAI-compatible chat endpoints"
```

---

### Task 2: Citation parsing and `ask()` orchestration

**Files:**
- Create: `backend/app/services/synthesis.py`

**Interfaces:**
- Consumes: `llm.chat`, `llm.LLMError`, `settings.gemini_*`, `retrieval.search(db, repo, question, top_k, mode) -> list[SearchHit]`, `SearchHit`
- Produces:
  - `synthesis.ABSTAIN_MESSAGE: str`
  - `synthesis.MissingApiKey(Exception)`
  - `synthesis.format_fragments(hits: list[SearchHit]) -> str`
  - `synthesis.parse_citations(text: str, n: int) -> tuple[str, list[int], int]` — (display text, 0-based hit indices in order of appearance, invalid count)
  - `synthesis.AskResult` dataclass: `answer: str`, `found: bool`, `sources: list[SearchHit]`, `retrieved: list[SearchHit]`, `invalid_citations: int`
  - `synthesis.ask(db: Session, repo: str, question: str, top_k: int = 5) -> AskResult` — raises `MissingApiKey` or `llm.LLMError`

- [ ] **Step 1: Write the self-check first, with a stub parser**

Create `backend/app/services/synthesis.py`:

```python
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


def parse_citations(text: str, n: int) -> tuple[str, list[int], int]:
    raise NotImplementedError


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
```

- [ ] **Step 2: Run it to see it fail**

Run: `docker compose exec backend python -m app.services.synthesis`
Expected: `NotImplementedError` (`ABSTAIN_MESSAGE` is referenced but never reached).

- [ ] **Step 3: Implement the parser, the prompt, and `ask()`**

Replace the stub `parse_citations` in `backend/app/services/synthesis.py` with the following block (keep `_self_check` and the `__main__` guard below it):

```python
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
```

- [ ] **Step 4: Run the self-check**

Run: `docker compose exec backend python -m app.services.synthesis`
Expected: `synthesis OK — parseo de citas`

- [ ] **Step 5: Confirm `MissingApiKey` without a key, and a real answer with one**

```bash
docker compose exec -e GEMINI_API_KEY= backend python -c "from app.core.database import SessionLocal; from app.services import synthesis; db = SessionLocal(); synthesis.ask(db, 'dasalalvear-arch/u-swap', 'como se hashean las contrasenas')"
```
Expected: traceback ending in `MissingApiKey: GEMINI_API_KEY no esta configurada`.

```bash
docker compose exec backend python -c "from app.core.database import SessionLocal; from app.services import synthesis; r = synthesis.ask(SessionLocal(), 'dasalalvear-arch/u-swap', 'que algoritmo se usa para hashear las contrasenas'); print(r.found, r.invalid_citations); print(r.answer); print([s.file_path for s in r.sources])"
```
Expected: `True 0`, an answer in Spanish with `[n]` markers, and a list of paths. If the repo is not indexed, index it first: `curl -X POST localhost:8000/repos -H "Content-Type: application/json" -d '{"url":"https://github.com/dasalalvear-arch/u-swap"}'`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/synthesis.py
git commit -m "feat: index-based citation parsing and LLM synthesis over retrieved chunks"
```

---

### Task 3: The `/ask` route

**Files:**
- Modify: `backend/app/schemas/repo.py`
- Create: `backend/app/api/routes/ask.py`
- Modify: `backend/app/main.py:6,47`

**Interfaces:**
- Consumes: `synthesis.ask`, `synthesis.MissingApiKey`, `llm.LLMError`, `retrieval.repo_exists(db, repo) -> bool`
- Produces: `POST /ask` taking `AskRequest {repo: str, question: str, top_k: int = 5}` and returning `AskResponse {answer: str, found: bool, sources: SearchHit[]}`

- [ ] **Step 1: Add the schemas**

Append to `backend/app/schemas/repo.py`:

```python
class AskRequest(BaseModel):
    repo: str
    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class AskResponse(BaseModel):
    answer: str
    found: bool  # False = se abstuvo
    # Si found: solo los citados, en el orden en que aparecen en `answer`, y
    # `[n]` en el texto es sources[n-1]. Si no: los recuperados, para que el
    # usuario vea igual el codigo que se encontro.
    sources: list[SearchHit]
```

- [ ] **Step 2: Write the route**

Create `backend/app/api/routes/ask.py`:

```python
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
```

- [ ] **Step 3: Register it**

In `backend/app/main.py`, change line 6 to:

```python
from app.api.routes import ask, repos, search
```

and add after the `search` router line:

```python
app.include_router(ask.router, prefix="/ask", tags=["ask"])
```

- [ ] **Step 4: Smoke test every row of the spec's error table**

The backend reloads on file change (mounted volume). Run each:

```bash
curl -s -X POST localhost:8000/ask -H "Content-Type: application/json" -d '{"repo":"dasalalvear-arch/u-swap","question":"donde se valida que el correo sea @utem.cl"}'
```
Expected: `200`, `"found":true`, `answer` with `[1]`-style markers, `sources[0].file_path` set.

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/ask -H "Content-Type: application/json" -d '{"repo":"nadie/nada","question":"x"}'
```
Expected: `404`

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/ask -H "Content-Type: application/json" -d '{"repo":"dasalalvear-arch/u-swap","question":""}'
```
Expected: `422`

503 without a key — recreate the backend with the key blanked, test, then restore:

```bash
GEMINI_API_KEY= docker compose up -d backend
curl -s -X POST localhost:8000/ask -H "Content-Type: application/json" -d '{"repo":"dasalalvear-arch/u-swap","question":"x"}'
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/search -H "Content-Type: application/json" -d '{"repo":"dasalalvear-arch/u-swap","question":"bcrypt"}'
docker compose up -d backend
```
Expected: `{"detail":"Falta configurar GEMINI_API_KEY en el backend"}`, then `200` for `/search`. (An exported shell variable overrides the root `.env` for Compose substitution; the last command restores it.)

502 — force a provider error with a bad model id. (`GEMINI_MODEL` comes from `.env.example` via `env_file`, not from shell substitution, so override it per-process instead of on `compose up`):

```bash
docker compose exec -e GEMINI_MODEL=no-existe backend python -c "from fastapi.testclient import TestClient; from app.main import app; r = TestClient(app).post('/ask', json={'repo':'dasalalvear-arch/u-swap','question':'bcrypt'}); print(r.status_code, r.json())"
```
Expected: `502 {'detail': 'El modelo no respondio. Intenta de nuevo.'}` — no Google error text in the body. (`TestClient` ships with FastAPI via `httpx`; if the import fails because `httpx` is missing, skip this check and note it in the report — do not add the dependency.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/repo.py backend/app/api/routes/ask.py backend/app/main.py
git commit -m "feat: POST /ask with 404/503/502 handling"
```

---

### Task 4: Mechanical evaluation

**Files:**
- Create: `backend/app/services/evaluate_ask.py`

**Interfaces:**
- Consumes: `evaluate.load_set(path) -> (repo, [(question, expected_paths)])`, `synthesis.ask`, `AskResult.retrieved / found / invalid_citations`
- Produces: `evaluate_ask.run(eval_path: Path) -> None`, CLI `python -m app.services.evaluate_ask eval/uswap.json`. Task 5 adds the judge into this same file.

- [ ] **Step 1: Write the harness**

Create `backend/app/services/evaluate_ask.py`:

```python
"""Mide /ask: si responde cuando debe, si se calla cuando debe, y si inventa citas.

Separado de evaluate.py porque necesita GEMINI_API_KEY: mezclarlos romperia la
evaluacion de recuperacion para quien no tenga credenciales.

Lo que debia hacer el modelo sale del mismo set: si el archivo esperado entro
en lo recuperado, debia responder; si no, debia abstenerse.

Las dos primeras metricas son un intercambio: un prompt mas miedoso sube una y
hunde la otra. Se leen juntas. Citas invalidas deberia ser 0; si no, es un bug
de prompt o de parseo.

    docker compose exec backend python -m app.services.evaluate_ask eval/uswap.json
"""
import sys
import time
from pathlib import Path

from app.core.config import settings
from app.core.database import SessionLocal
from app.services import retrieval, synthesis
from app.services.evaluate import load_set

TOP_K = 5
# repoqa: pausa fija entre preguntas para no chocar con el limite por minuto
# del plan gratuito de Gemini. Con un plan pago se puede bajar a 0.
PAUSE_SECONDS = 4.0


def _pct(part: int, whole: int) -> str:
    return f"{part}/{whole} ({100 * part // whole}%)" if whole else "0/0 (sin casos)"


def run(eval_path: Path) -> None:
    if not settings.gemini_api_key:
        sys.exit("Falta GEMINI_API_KEY. Esta evaluacion llama al modelo.")

    repo, questions = load_set(eval_path)
    db = SessionLocal()
    try:
        if not retrieval.repo_exists(db, repo):
            sys.exit(f"No hay chunks indexados para {repo}. Corre POST /repos primero.")

        print(f"\nRepo: {repo} | Modelo: {settings.gemini_model} | Preguntas: {len(questions)}\n")

        should_answer = answered = 0
        should_abstain = abstained = 0
        invalid_total = 0

        for i, (question, expected) in enumerate(questions):
            if i:
                time.sleep(PAUSE_SECONDS)
            result = synthesis.ask(db, repo, question, TOP_K)
            retrieved_ok = any(e in hit.file_path for hit in result.retrieved for e in expected)

            if retrieved_ok:
                should_answer += 1
                answered += result.found
                mark = "OK   " if result.found else "CALLO"
            else:
                should_abstain += 1
                abstained += not result.found
                mark = "OK   " if not result.found else "INVENTO?"
            invalid_total += result.invalid_citations

            cited = ", ".join(hit.file_path for hit in result.sources) if result.found else "-"
            print(f"  {mark:<8} {question[:48]:<48} citas: {cited}")
    finally:
        db.close()

    print(f"\n  Respondio cuando debia:   {_pct(answered, should_answer)}")
    print(f"  Se abstuvo cuando debia:  {_pct(abstained, should_abstain)}")
    print(f"  Citas invalidas:          {invalid_total}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    run(Path(sys.argv[1]))
```

Note on `INVENTO?`: the model answered although the expected file was not retrieved. It is marked with `?` because the answer may still be legitimately grounded in another fragment — the judge (Task 5) is what decides.

- [ ] **Step 2: Run it**

Run: `docker compose exec backend python -m app.services.evaluate_ask eval/uswap.json`
Expected: 15 lines, then the three metrics. `should_answer + should_abstain == 15`, and with hit@5 at 66% expect roughly 10 / 5. **`Citas invalidas` must be `0`.** If it is not, find the offending answer (add a temporary `print(result.answer)`), fix the prompt or the parser, and rerun — do not commit with a nonzero count. If you get `LLMError` with `429`, raise `PAUSE_SECONDS` and rerun.

- [ ] **Step 3: Confirm the retrieval eval still runs without a key**

Run: `docker compose exec -e GEMINI_API_KEY= backend python -m app.services.evaluate eval/uswap.json hybrid`
Expected: `acierto@1:  3/15 (20%)` and `acierto@5:  10/15 (66%)` — unchanged.

- [ ] **Step 4: Commit**

Write the three numbers from Step 2 into the commit body.

```bash
git add backend/app/services/evaluate_ask.py
git commit -m "feat: mechanical evaluation harness for /ask

Respondio cuando debia: X/Y. Se abstuvo cuando debia: X/Y. Citas invalidas: 0."
```

---

### Task 5: Groundedness judge

**Files:**
- Modify: `backend/app/services/evaluate_ask.py`

**Interfaces:**
- Consumes: `llm.chat`, `llm.LLMError`, `synthesis.format_fragments`, `settings.judge_*`
- Produces: `evaluate_ask.judge(answer: str, sources: list[SearchHit]) -> bool | None` — `True` grounded, `False` not, `None` unreadable judge output

- [ ] **Step 1: Add the judge and its self-check**

In `backend/app/services/evaluate_ask.py`, add `import json` to the imports, change the services import to `from app.services import llm, retrieval, synthesis`, add `from app.schemas.repo import SearchHit`, and add below `PAUSE_SECONDS`:

```python
JUDGE_PROMPT = """Eres un verificador. Recibes una respuesta sobre un repositorio de codigo y los fragmentos numerados en que debia basarse.

Divide la respuesta en afirmaciones. Para cada una, indica el numero del fragmento que la sostiene, o null si ninguno la sostiene. Juzga SOLO si los fragmentos la respaldan, no si es cierta en general.

Responde solo con JSON, sin texto alrededor:
{"claims": [{"claim": "...", "fragment": 1}]}"""


def _verdict(raw: str, n_sources: int) -> bool | None:
    """Fundamentada = toda afirmacion apunta a un fragmento existente.

    Se deriva de las afirmaciones en vez de pedirle un veredicto suelto: obliga
    al juez a trabajar en vez de opinar. None = salida ilegible, que se reporta
    aparte y nunca cuenta como fundamentada.
    """
    try:
        claims = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])["claims"]
        return bool(claims) and all(c["fragment"] in range(1, n_sources + 1) for c in claims)
    except (ValueError, KeyError, TypeError):
        return None


def judge(answer: str, sources: list[SearchHit]) -> bool | None:
    messages = [
        {"role": "system", "content": JUDGE_PROMPT},
        {"role": "user", "content": f"Fragmentos:\n\n{synthesis.format_fragments(sources)}\n\nRespuesta:\n{answer}"},
    ]
    try:
        raw = llm.chat(settings.judge_base_url, settings.judge_api_key, settings.judge_model, messages)
    except llm.LLMError as error:
        print(f"    (juez fallo: {error})")
        return None
    return _verdict(raw, len(sources))


def _self_check() -> None:
    ok = '{"claims": [{"claim": "usa bcrypt", "fragment": 1}, {"claim": "x", "fragment": 2}]}'
    assert _verdict(ok, 2) is True
    # Una afirmacion sin respaldo basta para que no este fundamentada.
    assert _verdict('{"claims": [{"claim": "a", "fragment": 1}, {"claim": "b", "fragment": null}]}', 2) is False
    # Un fragmento que no existe tampoco respalda nada.
    assert _verdict('{"claims": [{"claim": "a", "fragment": 3}]}', 2) is False
    # Sin afirmaciones no hay nada que valide la respuesta.
    assert _verdict('{"claims": []}', 2) is False
    # Texto alrededor del JSON (los modelos lo agregan) se tolera.
    assert _verdict("Aqui va:\n" + ok + "\nListo.", 2) is True
    # Basura = ilegible, no fundamentada.
    assert _verdict("no se", 2) is None
    assert _verdict('{"otra": 1}', 2) is None
    print("evaluate_ask OK — veredicto del juez")
```

Note on `bool` and `range`: `True in range(1, 3)` is `True` in Python because `True == 1`. A judge answering `"fragment": true` would pass. Accepted: it is an unlikely output and the self-check documents the contract; do not add type checks for it.

- [ ] **Step 2: Run the self-check (it fails until wired)**

Change the `__main__` block to:

```python
if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--check":
        _self_check()
    else:
        run(Path(sys.argv[1]))
```

Run: `docker compose exec backend python -m app.services.evaluate_ask --check`
Expected: `evaluate_ask OK — veredicto del juez`. If an assert fails, fix `_verdict`, not the assert.

- [ ] **Step 3: Wire the judge into `run()`**

In `run()`, before the loop, add:

```python
        use_judge = bool(settings.judge_api_key)
        grounded = judged = unreadable = 0
```

Inside the loop, after `invalid_total += result.invalid_citations`, add:

```python
            if use_judge and result.found:
                verdict = judge(result.answer, result.sources)
                if verdict is None:
                    unreadable += 1
                else:
                    judged += 1
                    grounded += verdict
                    mark += "" if verdict else " NO-FUND"
```

Move the `print(f"  {mark:<8} ...")` line so it runs after this block (it already does if you insert above it). After the three metric prints at the end, add:

```python
    if not use_judge:
        print("  Fundamentadas (juez):     omitido — falta JUDGE_API_KEY\n")
        return
    print(f"  Fundamentadas (juez):     {_pct(grounded, judged)}  [{settings.judge_model}]")
    if unreadable:
        print(f"  Juez ilegible:            {unreadable} (no cuentan como fundamentadas)")
    if "generativelanguage.googleapis.com" in settings.judge_base_url:
        print("  SESGO: el juez es de la misma familia que el modelo que responde.")
    print()
```

`use_judge`, `grounded`, `judged` and `unreadable` are defined inside the `try`; that is fine because the prints run after it in the same function scope.

- [ ] **Step 4: Run without a judge key**

Run: `docker compose exec backend python -m app.services.evaluate_ask eval/uswap.json`
Expected: same output as Task 4 plus `Fundamentadas (juez): omitido — falta JUDGE_API_KEY`.

- [ ] **Step 5: Run with a judge key (only if the user has provided one)**

If the root `.env` contains `JUDGE_API_KEY=...`, recreate the backend (`docker compose up -d backend`) and rerun Step 4's command. Expected: a `Fundamentadas (juez): X/Y [model]` line. If there is no key, skip this step and say so in the report — it is not a blocker (spec, "Si el juez no está configurado").

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/evaluate_ask.py
git commit -m "feat: optional groundedness judge in the /ask evaluation"
```

---

### Task 6: Frontend switches to `/ask`

**Files:**
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/pages/AskPage.tsx`

**Interfaces:**
- Consumes: `POST /ask` → `AskResponse {answer, found, sources}`
- Produces: `AskResponse` type; `Turn.found?: boolean`

- [ ] **Step 1: Types**

In `frontend/src/services/api.ts`, add after `SearchHit`:

```ts
/** Respuesta de /ask. Si `found`, `[n]` en `answer` es `sources[n-1]`; si no, `sources` son los recuperados. */
export type AskResponse = {
  answer: string;
  found: boolean;
  sources: SearchHit[];
};
```

and change `Turn` to:

```ts
/** Una entrada del historial. `hits` y `found` solo vienen en las del asistente. */
export type Turn = {
  role: "user" | "assistant";
  content: string;
  found?: boolean;
  hits?: SearchHit[];
};
```

- [ ] **Step 2: Call `/ask`**

In `frontend/src/pages/AskPage.tsx`, change the import to:

```tsx
import { isAxiosError } from "axios";
import { Send } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { api, AskResponse, RepoSummary, Turn } from "../services/api";
```

Replace the whole `try { ... } catch { ... }` block inside `ask()` with:

```tsx
    try {
      const response = await api.post<AskResponse>("/ask", {
        repo: activeRepo,
        question,
        top_k: 5,
      });
      const { answer, found, sources } = response.data;
      setTurns((current) => [
        ...current,
        { role: "assistant", content: answer, found, hits: sources },
      ]);
    } catch (error) {
      // 503 (falta la key) y 502 (fallo el modelo) traen un detail legible.
      const detail = isAxiosError(error) ? error.response?.data?.detail : undefined;
      setTurns((current) => [
        ...current,
        {
          role: "assistant",
          content:
            typeof detail === "string" ? detail : "Fallo la consulta. Revisa que el backend este arriba.",
        },
      ]);
    } finally {
```

- [ ] **Step 3: Render answer, numbered chips, and the abstention case**

Replace the `{turns.map(...)}` block with:

```tsx
              {turns.map((turn, index) => (
                <div key={index} className={turn.role === "user" ? "turn mine" : "turn"}>
                  <div style={{ whiteSpace: "pre-wrap" }}>{turn.content}</div>
                  {turn.found === false && turn.hits?.length ? (
                    <p className="muted">Fragmentos recuperados, por si sirven:</p>
                  ) : null}
                  {turn.hits?.map((hit, i) => (
                    <div key={`${hit.file_path}:${hit.line_start}`} className="hit">
                      <div className="sources">
                        <span className="source-chip">
                          {turn.found ? `[${i + 1}] ` : ""}
                          {hit.file_path}:{hit.line_start}-{hit.line_end}
                        </span>
                      </div>
                      <pre className="hit-code">{hit.content}</pre>
                    </div>
                  ))}
                </div>
              ))}
              {pending && <div className="turn muted">Leyendo el codigo...</div>}
```

The `score` line is dropped on purpose: next to a synthesized answer it is noise, and its unitless RRF value invites misreading.

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run build`
Expected: exits 0, `vite build` prints the bundle sizes. Fix any type error before continuing.

- [ ] **Step 5: Check it in the browser**

With `docker compose up` running, open `http://localhost:5173`, pick `dasalalvear-arch/u-swap` and ask:
1. `que algoritmo se usa para hashear las contrasenas` → answer with `[1]` markers; chips below start with `[1]`.
2. A question the repo cannot answer, e.g. `que base de datos de grafos usa el proyecto` → the abstention message, then "Fragmentos recuperados, por si sirven:" and unnumbered chips.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/services/api.ts frontend/src/pages/AskPage.tsx
git commit -m "feat: AskPage answers through /ask with numbered citations"
```

---

### Task 7: Documentation

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-07-27-ask-endpoint-design.md:4`

- [ ] **Step 1: README**

In the status table, mark `/ask` as built. In the results section, add the numbers from Task 4 (and Task 5 if a judge key existed), with the judge model name, and state that `Citas invalidas` was `0`. If the judge did not run, write that explicitly instead of leaving the row out. Add the run command:

```bash
docker compose exec backend python -m app.services.evaluate_ask eval/uswap.json
```

and the root `.env` keys a user needs: `GEMINI_API_KEY` (required for `/ask`), `JUDGE_API_KEY` (optional, evaluation only).

- [ ] **Step 2: CLAUDE.md**

- Pipeline block: `POST /ask ... [NOT BUILT]` → `[DONE]`.
- Replace the "Current state" paragraph: ingestion, retrieval and `/ask` work; the next open item is cross-encoder reranking (66% → 80% hit@5).
- Under Backend, one paragraph: `services/synthesis.py` owns the prompt and citation parsing (renumbered `[n]` ↔ `sources[n-1]`); `services/llm.py` is a stdlib client for any OpenAI-compatible endpoint, Gemini included; `/ask` returns retrieved fragments in `sources` when `found` is false.
- Under Measuring, add the `evaluate_ask` command and that it needs `GEMINI_API_KEY` while `evaluate` does not.
- Under Frontend, drop the sentence saying AskPage still calls `/search`.

- [ ] **Step 3: Spec status**

Change line 4 of the spec to `**Estado:** implementado (plan: docs/superpowers/plans/2026-11-07-ask-endpoint.md)`.

- [ ] **Step 4: Final verification**

```bash
docker compose exec backend python -m app.services.retrieval
docker compose exec backend python -m app.services.synthesis
docker compose exec backend python -m app.services.evaluate_ask --check
docker compose exec -e GEMINI_API_KEY= backend python -m app.services.evaluate eval/uswap.json hybrid
cd frontend && npm run build
```

Expected: three `OK` lines, `acierto@5: 10/15 (66%)`, and a clean build.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md docs/superpowers/specs/2026-07-27-ask-endpoint-design.md
git commit -m "docs: /ask is built — results, commands and keys"
```
