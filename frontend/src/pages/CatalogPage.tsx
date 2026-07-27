import { Search, Leaf, Recycle, Sprout, Info, Plus, MessageSquare } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ItemCard } from "../components/ItemCard";
import { api, Category, Item, User } from "../services/api";
import "../eco-theme.css";

type CatalogPageProps = {
  user: User | null;
};

type CatalogLocationState = {
  notice?: string;
};

const HERO_PHRASES = [
  "Dale una segunda vida a tus insumos académicos.",
  "Fomenta la economía circular en nuestra comunidad.",
  "Comparte conocimiento, recicla tus materiales.",
  "Intercambia recursos y apoya a tus compañeros."
];

export function CatalogPage({ user }: CatalogPageProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [items, setItems] = useState<Item[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [search, setSearch] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [notice, setNotice] = useState("");
  const [phraseIndex, setPhraseIndex] = useState(0);
  const [isVisible, setIsVisible] = useState(true);
  const [requestTarget, setRequestTarget] = useState<Item | null>(null);
  const [requestMessage, setRequestMessage] = useState("");

  useEffect(() => {
    const state = location.state as CatalogLocationState | null;
    if (!state?.notice) return;

    setNotice(state.notice);
    navigate("/", { replace: true, state: null });
  }, [location.state, navigate]);

  useEffect(() => {
    api.get<Category[]>("/categories").then((response) => setCategories(response.data));
  }, []);

  useEffect(() => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (categoryId) params.set("category_id", categoryId);

    api.get<Item[]>(`/items?${params.toString()}`).then((response) => setItems(response.data));
  }, [search, categoryId]);

  const stats = useMemo(
    () => ({
      available: items.filter((item) => item.status === "AVAILABLE").length,
      categories: new Set(items.map((item) => item.category.id)).size,
    }),
    [items],
  );

  // Efecto cíclico para cambiar el texto del Hero
  useEffect(() => {
    const interval = setInterval(() => {
      setIsVisible(false); // Inicia el fade-out
      setTimeout(() => {
        setPhraseIndex((prev) => (prev + 1) % HERO_PHRASES.length);
        setIsVisible(true); // Inicia el fade-in tras haber cambiado el texto
      }, 500); // Espera 500ms a que termine el fade-out
    }, 5000); // Se ejecuta cada 5 segundos

    return () => clearInterval(interval);
  }, []);

  function requestItem(item: Item) {
    if (!user) {
      setNotice("Inicia sesion para solicitar un intercambio.");
      return;
    }
    setRequestMessage("");
    setRequestTarget(item);
  }

  async function submitRequest() {
    if (!requestTarget) return;
    const message = requestMessage.trim();
    if (!message) return;
    await api.post("/matches", { item_id: requestTarget.id, message });
    setNotice(`Solicitud enviada por "${requestTarget.title}".`);
    setRequestTarget(null);
  }

  return (
    <section className="eco-workspace">
      <div className="eco-hero">
        <div className="eco-hero-text">
          <p className="eco-eyebrow">
            <Leaf size={18} /> Marketplace circular UTEM
          </p>
          <h1 className={`eco-fade-text ${isVisible ? "visible" : "hidden"}`}>
            {HERO_PHRASES[phraseIndex]}
          </h1>
          <p className="eco-hero-sub">
            Intercambia libros, apuntes y herramientas con tu comunidad. Sin pagos, dentro del campus.
          </p>
          <div className="eco-hero-actions">
            <Link className="eco-btn-primary" to="/publish">
              <Plus size={18} /> Publicar artículo
            </Link>
            <Link className="eco-btn-ghost" to="/matches">
              <MessageSquare size={18} /> Ver solicitudes
            </Link>
          </div>
        </div>

        <div className="eco-stats">
          <div className="eco-stat">
            <Sprout size={22} color="var(--eco-primary)" />
            <div>
              <strong>{stats.available}</strong>
              <span>Disponibles</span>
            </div>
          </div>
          <div className="eco-stat">
            <Leaf size={22} color="var(--eco-primary)" />
            <div>
              <strong>{stats.categories}</strong>
              <span>Categorías activas</span>
            </div>
          </div>
          <div className="eco-stat">
            <Recycle size={22} color="var(--eco-primary)" />
            <div>
              <strong>0 CLP</strong>
              <span>Sin pagos</span>
            </div>
          </div>
        </div>
      </div>

      <label className="eco-search">
        <Search size={20} color="var(--eco-primary)" />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Buscar libros, calculadoras, apuntes..."
        />
      </label>

      <div className="eco-chips">
        <button
          type="button"
          className={categoryId === "" ? "eco-chip active" : "eco-chip"}
          onClick={() => setCategoryId("")}
        >
          Todas
        </button>
        {categories.map((category) => (
          <button
            type="button"
            key={category.id}
            className={categoryId === String(category.id) ? "eco-chip active" : "eco-chip"}
            onClick={() => setCategoryId(String(category.id))}
          >
            {category.name}
          </button>
        ))}
      </div>

      {notice && <p className="eco-notice"><Info size={20} /> {notice}</p>}

      <div className="item-grid">
        {items.map((item) => (
          <ItemCard
            key={item.id}
            item={item}
            disabled={user?.id === item.owner.id}
            onRequest={requestItem}
          />
        ))}
        {items.length === 0 && (
          <div className="empty-state">
            <h2>Aun no hay publicaciones.</h2>
            <p>La primera publicacion puede ser un libro, calculadora, set de plumones o material de laboratorio.</p>
          </div>
        )}
      </div>

      {requestTarget && (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          onClick={() => setRequestTarget(null)}
        >
          <div className="modal-card" onClick={(event) => event.stopPropagation()}>
            <h3>Solicitar "{requestTarget.title}"</h3>
            <p className="muted">Escribe un mensaje al donante para coordinar el intercambio.</p>
            <textarea
              autoFocus
              rows={4}
              value={requestMessage}
              onChange={(event) => setRequestMessage(event.target.value)}
              placeholder="Hola, me interesa este artículo. ¿Sigue disponible?"
            />
            <div className="modal-actions">
              <button type="button" className="eco-btn-ghost" onClick={() => setRequestTarget(null)}>
                Cancelar
              </button>
              <button
                type="button"
                className="eco-btn-primary"
                disabled={!requestMessage.trim()}
                onClick={submitRequest}
              >
                <MessageSquare size={18} /> Enviar solicitud
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
