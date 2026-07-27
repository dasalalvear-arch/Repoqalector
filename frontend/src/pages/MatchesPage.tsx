import { Send } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { api, Match, Message, User } from "../services/api";

type MatchesPageProps = {
  user: User;
};

export function MatchesPage({ user }: MatchesPageProps) {
  const [matches, setMatches] = useState<Match[]>([]);
  const [activeMatch, setActiveMatch] = useState<Match | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);

  useEffect(() => {
    api.get<Match[]>("/matches").then((response) => {
      setMatches(response.data);
      setActiveMatch(response.data[0] ?? null);
    });
  }, []);

  useEffect(() => {
    if (!activeMatch) return;
    api.get<Message[]>(`/chat/${activeMatch.id}`).then((response) => setMessages(response.data));
  }, [activeMatch]);

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeMatch) return;

    // Capturamos el form antes del await: tras la llamada async,
    // event.currentTarget ya es null y el reset() no limpiaria el input.
    const formEl = event.currentTarget;
    const content = String(new FormData(formEl).get("content") ?? "").trim();
    if (!content) return;

    const response = await api.post<Message>(`/chat/${activeMatch.id}`, { content });
    setMessages((current) => [...current, response.data]);
    formEl.reset();
  }

  return (
    <section className="matches-layout">
      <aside className="matches-list">
        <div className="section-heading small">
          <p className="eyebrow">Coordinacion</p>
          <h1>Solicitudes</h1>
        </div>
        {matches.map((match) => (
          <button
            key={match.id}
            className={activeMatch?.id === match.id ? "match-row active" : "match-row"}
            onClick={() => setActiveMatch(match)}
          >
            <span className="match-row-item">{match.item.title}</span>
            <span className="muted">Solicitado por {match.requester.name}</span>
            <strong>{match.status}</strong>
          </button>
        ))}
        {matches.length === 0 && <p className="muted">No hay solicitudes todavia.</p>}
      </aside>
      <div className="chat-panel">
        {activeMatch ? (
          <>
            <div className="chat-header">
              <span>
                {activeMatch.item.title} · Solicitado por {activeMatch.requester.name}
              </span>
              <strong>{activeMatch.status}</strong>
            </div>
            <div className="message-list">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={message.sender_id === user.id ? "message mine" : "message"}
                >
                  {message.content}
                </div>
              ))}
            </div>
            <form className="message-form" onSubmit={sendMessage}>
              <input name="content" placeholder="Coordinar punto y horario dentro del campus" />
              <button className="icon-button" title="Enviar">
                <Send size={18} />
              </button>
            </form>
          </>
        ) : (
          <div className="empty-state">
            <h2>Selecciona una solicitud.</h2>
            <p>Cuando solicites o recibas una solicitud, el chat aparecera aqui.</p>
          </div>
        )}
      </div>
    </section>
  );
}
