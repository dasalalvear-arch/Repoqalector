"""Mide /ask: si responde cuando debe, si se calla cuando debe, y si inventa citas.

Separado de evaluate.py porque necesita GEMINI_API_KEY: mezclarlos romperia la
evaluacion de recuperacion para quien no tenga credenciales.

Lo que debia hacer el modelo sale del mismo set: si el archivo esperado entro
en lo recuperado, debia responder; si no, debia abstenerse.

Las dos primeras metricas son un intercambio: un prompt mas miedoso sube una y
hunde la otra. Se leen juntas. Citas invalidas deberia ser 0; si no, es un bug
de prompt o de parseo.

Generar y medir estan separados. El plan gratuito de Gemini da ~20 consultas
por dia por modelo y una corrida son 15, asi que cada respuesta se guarda en
`eval/<set>.answers.json` apenas llega: si la cuota se corta a mitad, la
siguiente corrida retoma donde quedo en vez de volver a pagar lo ya generado.
Las metricas (y el juez) se calculan desde ese archivo, sin llamar a Gemini.

El juez (opcional, JUDGE_API_KEY) verifica que cada afirmacion de la respuesta
este respaldada por un fragmento citado. Su veredicto tambien se guarda, asi
que volver a correr no lo vuelve a pagar.

Si cambia el modelo o el prompt, las respuestas guardadas se descartan solas.
Si cambia la recuperacion (pesos, reindexado), borra el archivo a mano.

    docker compose exec backend python -m app.services.evaluate_ask eval/uswap.json
    docker compose exec backend python -m app.services.evaluate_ask --check
"""
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

from app.core.config import settings
from app.core.database import SessionLocal
from app.schemas.repo import SearchHit
from app.services import llm, retrieval, synthesis
from app.services.evaluate import load_set

TOP_K = 5
# repoqa: pausa fija entre llamadas para el limite por minuto del plan
# gratuito. No protege del limite diario: eso lo cubre guardar y retomar.
# Con un plan pago se puede bajar a 0.
PAUSE_SECONDS = 13.0

# Limite por minuto del proveedor del juez (Groq gratis: 30/min).
JUDGE_PAUSE_SECONDS = 3.0

JUDGE_PROMPT = """Eres un verificador. Recibes una respuesta sobre un repositorio de codigo y los fragmentos numerados en que debia basarse.

Divide la respuesta en afirmaciones. Para cada una, indica el numero del fragmento que la sostiene, o null si ninguno la sostiene. Juzga SOLO si los fragmentos la respaldan, no si es cierta en general.

Responde solo con JSON, sin texto alrededor:
{"claims": [{"claim": "...", "fragment": 1}]}"""

Questions = list[tuple[str, list[str]]]


def _pct(part: int, whole: int) -> str:
    return f"{part}/{whole} ({100 * part // whole}%)" if whole else "0/0 (sin casos)"


def _fingerprint() -> str:
    """Respuestas de otro modelo u otro prompt no son comparables con las nuevas."""
    text = f"{settings.gemini_model}\n{synthesis.SYSTEM_PROMPT}"
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _load_answers(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("fingerprint") != _fingerprint():
        print("  El modelo o el prompt cambiaron: se descartan las respuestas guardadas.")
        return {}
    return data["answers"]


def _save_answers(path: Path, answers: dict[str, dict]) -> None:
    data = {"fingerprint": _fingerprint(), "model": settings.gemini_model, "answers": answers}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def generate(eval_path: Path) -> tuple[Questions, dict[str, dict]]:
    """Genera solo las respuestas que faltan; ante un error del modelo se detiene sin perder nada."""
    repo, questions = load_set(eval_path)
    path = eval_path.with_suffix(".answers.json")
    answers = _load_answers(path)
    pending = [question for question, _ in questions if question not in answers]

    print(f"\nRepo: {repo} | Modelo: {settings.gemini_model}")
    print(f"Guardadas: {len(questions) - len(pending)} | Por generar: {len(pending)}\n")
    if not pending:
        return questions, answers
    if not settings.gemini_api_key:
        sys.exit("Falta GEMINI_API_KEY para generar las respuestas que faltan.")

    db = SessionLocal()
    try:
        if not retrieval.repo_exists(db, repo):
            sys.exit(f"No hay chunks indexados para {repo}. Corre POST /repos primero.")
        for i, question in enumerate(pending):
            if i:
                time.sleep(PAUSE_SECONDS)
            try:
                result = synthesis.ask(db, repo, question, TOP_K)
            except llm.LLMError as error:
                # Un limite diario no se arregla reintentando: se corta aqui y
                # la proxima corrida sigue desde esta pregunta.
                print(f"  Detenido en {i + 1}/{len(pending)}: {str(error)[:200]}")
                print("  Lo generado quedo guardado; vuelve a correr para continuar.\n")
                break
            answers[question] = {
                "retrieved": [hit.file_path for hit in result.retrieved],
                "found": result.found,
                "answer": result.answer,
                "invalid_citations": result.invalid_citations,
                "sources": [hit.model_dump() for hit in result.sources],
            }
            # Tras cada respuesta: un corte a mitad no pierde lo ya pagado.
            _save_answers(path, answers)
    finally:
        db.close()
    return questions, answers


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


def _judged(record: dict) -> bool:
    """Tiene veredicto guardado del juez configurado ahora (otro juez no cuenta)."""
    return record["found"] and record.get("judge", {}).get("model") == settings.judge_model


def judge_saved(eval_path: Path, answers: dict[str, dict]) -> None:
    """Juzga las respuestas guardadas que faltan. Gasta cuota del juez, nunca de Gemini."""
    if not settings.judge_api_key:
        return
    path = eval_path.with_suffix(".answers.json")
    pending = [r for r in answers.values() if r["found"] and not _judged(r)]
    for i, record in enumerate(pending):
        if i:
            time.sleep(JUDGE_PAUSE_SECONDS)
        hits = [SearchHit(**source) for source in record["sources"]]
        messages = [
            {"role": "system", "content": JUDGE_PROMPT},
            {
                "role": "user",
                "content": f"Fragmentos:\n\n{synthesis.format_fragments(hits)}\n\nRespuesta:\n{record['answer']}",
            },
        ]
        try:
            raw = llm.chat(settings.judge_base_url, settings.judge_api_key, settings.judge_model, messages)
        except llm.LLMError as error:
            print(f"  Juez detenido en {i + 1}/{len(pending)}: {str(error)[:200]}\n")
            break
        record["judge"] = {"model": settings.judge_model, "grounded": _verdict(raw, len(hits))}
        _save_answers(path, answers)


def _retrieved_ok(record: dict, expected: list[str]) -> bool:
    return any(e in path for path in record["retrieved"] for e in expected)


def _mark(record: dict | None, expected: list[str]) -> str:
    if record is None:
        return "FALTA"
    if _retrieved_ok(record, expected):
        return "OK" if record["found"] else "CALLO"
    # Respondio sin que el archivo esperado se recuperara. El "?" es porque
    # puede estar bien fundamentada en otro fragmento: eso lo decide el juez.
    return "OK" if not record["found"] else "INVENTO?"


def summarize(questions: Questions, answers: dict[str, dict]) -> dict[str, int]:
    """Metricas desde las respuestas guardadas. No llama a nada."""
    counts = dict.fromkeys(
        ("should_answer", "answered", "should_abstain", "abstained", "invalid", "missing"), 0
    )
    for question, expected in questions:
        record = answers.get(question)
        if record is None:
            counts["missing"] += 1
            continue
        if _retrieved_ok(record, expected):
            counts["should_answer"] += 1
            counts["answered"] += record["found"]
        else:
            counts["should_abstain"] += 1
            counts["abstained"] += not record["found"]
        counts["invalid"] += record["invalid_citations"]
    return counts


def report(questions: Questions, answers: dict[str, dict]) -> None:
    for question, expected in questions:
        record = answers.get(question)
        found = record is not None and record["found"]
        cited = ", ".join(source["file_path"] for source in record["sources"]) if found else "-"
        mark = _mark(record, expected)
        if found and _judged(record) and record["judge"]["grounded"] is False:
            mark += " NO-FUND"
        print(f"  {mark:<16} {question[:48]:<48} citas: {cited}")

    counts = summarize(questions, answers)
    print(f"\n  Respondio cuando debia:   {_pct(counts['answered'], counts['should_answer'])}")
    print(f"  Se abstuvo cuando debia:  {_pct(counts['abstained'], counts['should_abstain'])}")
    print(f"  Citas invalidas:          {counts['invalid']}")
    verdicts = [r["judge"]["grounded"] for r in answers.values() if _judged(r)]
    if verdicts:
        readable = [v for v in verdicts if v is not None]
        print(f"  Fundamentadas (juez):     {_pct(sum(readable), len(readable))}  [{settings.judge_model}]")
        if len(readable) < len(verdicts):
            print(f"  Juez ilegible:            {len(verdicts) - len(readable)} (no cuentan como fundamentadas)")
        if "generativelanguage.googleapis.com" in settings.judge_base_url:
            print("  SESGO: el juez es de la misma familia que el modelo que responde.")
    else:
        print("  Fundamentadas (juez):     omitido — falta JUDGE_API_KEY")
    if counts["missing"]:
        print(f"\n  PARCIAL: faltan {counts['missing']} de {len(questions)}. No reportar estos numeros.")
    print()


def _self_check() -> None:
    def record(retrieved: list[str], found: bool, invalid: int = 0) -> dict:
        return {
            "retrieved": retrieved,
            "found": found,
            "answer": "",
            "invalid_citations": invalid,
            "sources": [],
        }

    questions = [
        ("q1", ["auth.py"]),  # recuperado y respondio: bien
        ("q2", ["seed.py"]),  # recuperado y se callo: mal
        ("q3", ["chat.py"]),  # no recuperado y se callo: bien
        ("q4", ["admin.py"]),  # no recuperado y respondio: sospechoso
        ("q5", ["x.py"]),  # todavia sin generar
    ]
    answers = {
        "q1": record(["routes/auth.py"], True, invalid=2),
        "q2": record(["services/seed.py", "README.md"], False),
        "q3": record(["README.md"], False),
        "q4": record(["README.md"], True),
    }

    counts = summarize(questions, answers)
    assert counts == {
        "should_answer": 2,
        "answered": 1,
        "should_abstain": 2,
        "abstained": 1,
        "invalid": 2,
        "missing": 1,
    }, counts

    assert _mark(answers["q1"], ["auth.py"]) == "OK"
    assert _mark(answers["q2"], ["seed.py"]) == "CALLO"
    assert _mark(answers["q3"], ["chat.py"]) == "OK"
    assert _mark(answers["q4"], ["admin.py"]) == "INVENTO?"
    assert _mark(None, ["x.py"]) == "FALTA"

    # Retomar: lo guardado se recupera tal cual...
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "set.answers.json"
        _save_answers(path, answers)
        assert _load_answers(path) == answers
        # ...salvo que lo haya generado otro modelo u otro prompt.
        path.write_text(json.dumps({"fingerprint": "otro", "answers": answers}), encoding="utf-8")
        assert _load_answers(path) == {}

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

    print("evaluate_ask OK — metricas desde respuestas guardadas y veredicto del juez")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--check":
        _self_check()
    else:
        eval_path = Path(sys.argv[1])
        questions, answers = generate(eval_path)
        judge_saved(eval_path, answers)
        report(questions, answers)
