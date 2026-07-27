import { Send } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { Answer, api, Turn } from "../services/api";

export function AskPage() {
  const [repos, setRepos] = useState<string[]>([]);
  const [activeRepo, setActiveRepo] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    api.get<string[]>("/repos").then((response) => {
      setRepos(response.data);
      setActiveRepo(response.data[0] ?? null);
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
      const response = await api.post<Answer>("/ask", { repo: activeRepo, question });
      setTurns((current) => [
        ...current,
        { role: "assistant", content: response.data.answer, sources: response.data.sources },
      ]);
    } catch {
      setTurns((current) => [
        ...current,
        { role: "assistant", content: "No se pudo obtener respuesta. Revisa que el backend este arriba." },
      ]);
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="matches-layout">
      <aside className="matches-list">
        <div className="section-heading small">
          <p className="eyebrow">Indexados</p>
          <h1>Repositorios</h1>
        </div>
        {repos.map((repo) => (
          <button
            key={repo}
            className={activeRepo === repo ? "match-row active" : "match-row"}
            onClick={() => setActiveRepo(repo)}
          >
            <span className="match-row-item">{repo}</span>
          </button>
        ))}
        {repos.length === 0 && <p className="muted">No hay repositorios indexados todavia.</p>}
      </aside>
      <div className="chat-panel">
        {activeRepo ? (
          <>
            <div className="chat-header">
              <span>{activeRepo}</span>
            </div>
            <div className="message-list">
              {turns.map((turn, index) => (
                <div key={index} className={turn.role === "user" ? "message mine" : "message"}>
                  {turn.content}
                  {turn.sources && turn.sources.length > 0 && (
                    <div className="sources">
                      {turn.sources.map((source) => (
                        <span
                          key={`${source.file_path}:${source.line_start}`}
                          className="source-chip"
                        >
                          {source.file_path}:{source.line_start}-{source.line_end}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              {pending && <div className="message muted">Buscando en el codigo...</div>}
            </div>
            <form className="message-form" onSubmit={ask}>
              <input name="question" placeholder="Pregunta algo sobre este repositorio" />
              <button className="icon-button" title="Preguntar" disabled={pending}>
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
