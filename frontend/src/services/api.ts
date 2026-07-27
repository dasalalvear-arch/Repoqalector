import axios from "axios";

export type Category = {
  id: number;
  name: string;
};

export type User = {
  id: number;
  name: string;
  email: string;
  career: string | null;
  role: "STUDENT" | "ADMIN";
};

export type Item = {
  id: number;
  title: string;
  description: string;
  condition: string;
  status: "AVAILABLE" | "RESERVED" | "DELIVERED";
  category: Category;
  owner: User;
  images: { id: number; image_url: string }[];
  created_at: string;
};

export type Match = {
  id: number;
  item_id: number;
  requester_id: number;
  owner_id: number;
  status: "PENDING" | "ACCEPTED" | "REJECTED" | "COMPLETED";
  created_at: string;
  requester: { id: number; name: string };
  item: { id: number; title: string };
};

export type Message = {
  id: number;
  match_id: number;
  sender_id: number;
  content: string;
  created_at: string;
};

export type Metrics = {
  registered_users: number;
  active_listings: number;
  matches_generated: number;
  completed_exchanges: number;
};

export const TOKEN_KEY = "uswap.token";
export const UNAUTHORIZED_EVENT = "uswap:unauthorized";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Si el backend responde 401 teniendo una sesion activa, el token expiro o
// fue revocado: lo limpiamos y avisamos a la app para cerrar sesion. No se
// dispara en el login (ahi no hay token y el formulario maneja el error).
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const hadSession = localStorage.getItem(TOKEN_KEY) !== null;
    if (error.response?.status === 401 && hadSession) {
      localStorage.removeItem(TOKEN_KEY);
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    return Promise.reject(error);
  },
);
