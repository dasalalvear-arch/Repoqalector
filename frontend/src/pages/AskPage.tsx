import { isAxiosError } from "axios";
import { Send } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { api, AskResponse, RepoSummary, Turn } from "../services/api";

export function AskPage() {
  const [repos, setRepos] = useState<RepoSummary[]>([]);
  const [activeRepo, setActiveRepo] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    api.get<RepoSummary[]>("/repos").then((response) => {
      setRepos(response.data);
      setActiveRepo(response.data[0]?.repo ?? null);
    });
  }, []);

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeRepo || pending) return;

    // Capturamos el form antes del await: tras la llamada async,
    // event.currentTarget ya es null y el reset() no limpiaria el input.
    const formEl = event.currentTarget;
    const question = String(new FormData(formEl).get("question") ?? "").trim();
    if (!question) return;

    formEl.reset();
    setTurns((current) => [...current, { role: "user", content: question }]);
    setPending(true);
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
      setPending(false);
    }
  }

  return (
    <section className="ask-layout">
      <aside className="repo-list">
        <div className="section-heading small">
          <p className="eyebrow">Indexados</p>
          <h1>Repositorios</h1>
        </div>
        {repos.map((item) => (
          <button
            key={item.repo}
            className={activeRepo === item.repo ? "repo-row active" : "repo-row"}
            onClick={() => setActiveRepo(item.repo)}
          >
            <span className="repo-name">{item.repo}</span>
            <span className="muted">{item.chunks} fragmentos</span>
          </button>
        ))}
        {repos.length === 0 && <p className="muted">No hay repositorios indexados todavia.</p>}
      </aside>
      <div className="answer-panel">
        {activeRepo ? (
          <>
            <div className="answer-header">
              <span>{activeRepo}</span>
            </div>
            <div className="thread">
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
            </div>
            <form className="ask-form" onSubmit={ask}>
              <input name="question" placeholder="Pregunta algo sobre este repositorio" />
              <button className="icon-button" title="Buscar" disabled={pending}>
                <Send size={18} />
              </button>
            </form>
          </>
        ) : (
          <div className="empty-state">
            <h2>Todavia no hay nada indexado.</h2>
            <p>Indexa un repositorio con POST /repos para empezar a preguntar.</p>
          </div>
        )}
      </div>
    </section>
  );
}
