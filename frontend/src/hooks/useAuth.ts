import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, TOKEN_KEY, UNAUTHORIZED_EVENT, User } from "../services/api";

type AuthState = {
  user: User | null;
  token: string | null;
  loading: boolean;
};

export function useAuth() {
  const navigate = useNavigate();
  const [state, setState] = useState<AuthState>({
    user: null,
    token: localStorage.getItem(TOKEN_KEY),
    loading: true,
  });

  useEffect(() => {
    if (!state.token) {
      setState((current) => ({ ...current, loading: false }));
      return;
    }

    api
      .get<User>("/auth/me")
      .then((response) => {
        setState({ user: response.data, token: state.token, loading: false });
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        setState({ user: null, token: null, loading: false });
      });
  }, [state.token]);

  // El interceptor de axios emite este evento cuando el token expira (401).
  // Reseteamos el estado para que la app refleje la sesion cerrada.
  useEffect(() => {
    function handleUnauthorized() {
      setState({ user: null, token: null, loading: false });
    }
    window.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
  }, []);

  // Devuelve el rol para que App.tsx redirija segun student/admin.
  async function login(email: string, password: string): Promise<string> {
    const response = await api.post<{ access_token: string }>("/auth/login", { email, password });
    localStorage.setItem(TOKEN_KEY, response.data.access_token);

    const meResponse = await api.get<User>("/auth/me", {
      headers: { Authorization: `Bearer ${response.data.access_token}` },
    });

    setState({ user: meResponse.data, token: response.data.access_token, loading: false });
    return meResponse.data.role;
  }


  async function register(name: string, email: string, password: string, career: string) {
    const response = await api.post<{ access_token: string }>("/auth/register", {
      name,
      email,
      password,
      career,
    });
    localStorage.setItem(TOKEN_KEY, response.data.access_token);
    setState((current) => ({ ...current, token: response.data.access_token, loading: true }));
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    setState({ user: null, token: null, loading: false });
    navigate("/auth");
  }

  return { ...state, login, register, logout };
}