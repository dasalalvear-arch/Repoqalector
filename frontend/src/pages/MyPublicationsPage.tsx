import { CheckCircle, Package, Pencil, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, Item, User } from "../services/api";
import "../eco-theme.css";

type MyPublicationsPageProps = {
  user: User;
};

const STATUS_LABEL: Record<string, string> = {
  AVAILABLE: "Disponible",
  RESERVED: "Reservado",
  DELIVERED: "Entregado",
};

const STATUS_CLASS: Record<string, string> = {
  AVAILABLE: "available",
  RESERVED: "reserved",
  DELIVERED: "delivered",
};

export function MyPublicationsPage({ user }: MyPublicationsPageProps) {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");

  function load() {
    setLoading(true);
    api
      .get<Item[]>(`/items?owner_id=${user.id}&limit=100`)
      .then((response) => setItems(response.data))
      .catch(() => setNotice("No se pudieron cargar tus publicaciones."))
      .finally(() => setLoading(false));
  }

  useEffect(load, [user.id]);

  const summary = useMemo(
    () => ({
      total: items.length,
      available: items.filter((item) => item.status === "AVAILABLE").length,
    }),
    [items],
  );

  async function setStatus(item: Item, status: "AVAILABLE" | "DELIVERED") {
    try {
      await api.put(`/items/${item.id}`, { status });
      setNotice(
        status === "DELIVERED"
          ? `"${item.title}" marcado como entregado.`
          : `"${item.title}" reactivado.`,
      );
      load();
    } catch {
      setNotice(`No se pudo actualizar "${item.title}".`);
    }
  }

  async function remove(item: Item) {
    if (!window.confirm(`¿Eliminar "${item.title}"?`)) return;
    try {
      await api.delete(`/items/${item.id}`);
      setNotice(`"${item.title}" eliminado.`);
      load();
    } catch {
      setNotice(`No se pudo eliminar "${item.title}".`);
    }
  }

  return (
    <section className="mine-page">
      <div className="mine-head">
        <div>
          <h1>Mis publicaciones</h1>
          <p>
            {summary.total} publicacion(es) · {summary.available} disponible(s)
          </p>
        </div>
        <Link className="eco-btn-primary" to="/publish">
          <Plus size={18} /> Publicar artículo
        </Link>
      </div>

      {notice && <p className="eco-notice">{notice}</p>}

      {loading ? (
        <p className="muted">Cargando...</p>
      ) : items.length === 0 ? (
        <div className="mine-empty">
          <h2>Aún no has publicado nada.</h2>
          <p>Comparte tu primer libro, calculadora o material con la comunidad.</p>
          <Link className="eco-btn-primary" to="/publish">
            <Plus size={18} /> Publicar tu primer artículo
          </Link>
        </div>
      ) : (
        <div className="mine-list">
          {items.map((item) => (
            <div className="mine-row" key={item.id}>
              <span className="mine-thumb">
                {item.images[0] ? <img src={item.images[0].image_url} alt="" /> : <Package size={22} />}
              </span>
              <div className="mine-info">
                <h3>{item.title}</h3>
                <span>
                  {item.category.name} · {item.condition}
                </span>
              </div>
              <span className={`mine-status ${STATUS_CLASS[item.status]}`}>
                {STATUS_LABEL[item.status]}
              </span>
              <div className="mine-actions">
                <Link className="mine-btn" to={`/publish/${item.id}`}>
                  <Pencil size={14} /> Editar
                </Link>
                {item.status === "DELIVERED" ? (
                  <button className="mine-btn" onClick={() => setStatus(item, "AVAILABLE")}>
                    <RotateCcw size={14} /> Reactivar
                  </button>
                ) : (
                  <button className="mine-btn" onClick={() => setStatus(item, "DELIVERED")}>
                    <CheckCircle size={14} /> Marcar entregado
                  </button>
                )}
                <button className="mine-btn danger" onClick={() => remove(item)}>
                  <Trash2 size={14} /> Eliminar
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
