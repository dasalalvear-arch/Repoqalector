import { Check, EyeOff, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, Metrics, User } from "../services/api";

type AdminItem = {
  id: number;
  title: string;
  category: { name: string } | null;
  moderation_status: string;
  owner: { name: string; email: string } | null;
  created_at: string;
  images: { image_url: string }[];
};

type AdminPageProps = {
  user: User;
};

const METRIC_CARDS = [
  { key: "registered_users", label: "Usuarios registrados" },
  { key: "active_listings", label: "Publicaciones activas" },
  { key: "matches_generated", label: "Solicitudes generadas" },
  { key: "completed_exchanges", label: "Intercambios completados" },
] as const;

export function AdminPage({ user }: AdminPageProps) {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [items, setItems] = useState<AdminItem[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [userError, setUserError] = useState("");

  async function fetchItems() {
    setLoading(true);
    const params = new URLSearchParams();
    if (search) params.append("search", search);
    if (statusFilter) params.append("status", statusFilter);
    const res = await api.get<AdminItem[]>(`/admin/items?${params.toString()}`);
    setItems(res.data);
    setLoading(false);
  }

  function fetchMetrics() {
    api.get<Metrics>("/admin/metrics").then((res) => setMetrics(res.data));
  }

  function fetchUsers() {
    api.get<User[]>("/admin/users").then((res) => setUsers(res.data));
  }

  useEffect(() => {
    fetchItems();
    fetchMetrics();
    fetchUsers();
  }, []);

  async function handleAction(id: number, action: "approve" | "hide" | "delete") {
    if (action === "delete") {
      await api.delete(`/admin/items/${id}`);
    } else {
      await api.put(`/admin/items/${id}/${action}`);
    }
    fetchItems();
    fetchMetrics();
  }

  async function removeUser(target: User) {
    setUserError("");
    if (!window.confirm(`¿Eliminar a ${target.name} (${target.email})?`)) return;
    try {
      await api.delete(`/admin/users/${target.id}`);
      fetchUsers();
      fetchMetrics();
    } catch {
      setUserError("No se pudo eliminar el usuario.");
    }
  }

  return (
    <div className="admin-panel">
      <h1>Panel de Administración</h1>

      <div className="metrics-row">
        {METRIC_CARDS.map(({ key, label }) => (
          <div key={key}>
            <strong>{metrics ? metrics[key] : "-"}</strong>
            <span>{label}</span>
          </div>
        ))}
      </div>

      <h2>Moderación de publicaciones</h2>
      <div className="admin-filters">
        <input
          placeholder="Buscar por título..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">Todos los estados</option>
          <option value="pending">Pendiente</option>
          <option value="approved">Aprobado</option>
          <option value="hidden">Oculto</option>
        </select>
        <button onClick={fetchItems}>Filtrar</button>
      </div>

      {loading ? (
        <p>Cargando...</p>
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Imagen</th>
              <th>Título</th>
              <th>Categoría</th>
              <th>Estado</th>
              <th>Autor</th>
              <th>Correo</th>
              <th>Fecha</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>
                  {item.images[0] && (
                    <img src={item.images[0].image_url} alt={item.title} width={50} height={50} style={{ objectFit: "cover" }} />
                  )}
                </td>
                <td>{item.title}</td>
                <td>{item.category?.name ?? "-"}</td>
                <td>{item.moderation_status}</td>
                <td>{item.owner?.name ?? "-"}</td>
                <td>{item.owner?.email ?? "-"}</td>
                <td>{new Date(item.created_at).toLocaleDateString("es-CL")}</td>
                <td className="admin-actions">
                  <button onClick={() => handleAction(item.id, "approve")}><Check size={15} /> Aprobar</button>
                  <button onClick={() => handleAction(item.id, "hide")}><EyeOff size={15} /> Ocultar</button>
                  <button className="danger" onClick={() => handleAction(item.id, "delete")}><Trash2 size={15} /> Eliminar</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Usuarios</h2>
      {userError && <p className="form-error">{userError}</p>}
      <table className="admin-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Nombre</th>
            <th>Correo</th>
            <th>Carrera</th>
            <th>Rol</th>
            <th>Acciones</th>
          </tr>
        </thead>
        <tbody>
          {users.map((row) => (
            <tr key={row.id}>
              <td>{row.id}</td>
              <td>{row.name}</td>
              <td>{row.email}</td>
              <td>{row.career ?? "-"}</td>
              <td>{row.role === "ADMIN" ? "Administrador" : "Estudiante"}</td>
              <td className="admin-actions">
                {row.id !== user.id && (
                  <button className="danger" onClick={() => removeUser(row)}><Trash2 size={15} /> Eliminar</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
