import { AlertCircle, BookOpen, LayoutList, LogOut, Plus, RefreshCcw, Search, Shield } from "lucide-react";
import { Link, NavLink } from "react-router-dom";

import { User } from "../services/api";

type HeaderProps = {
  user: User | null;
  onLogout: () => void;
  pendingMatches?: number;
};

export function Header({ user, onLogout, pendingMatches = 0 }: HeaderProps) {
  return (
    <header className="app-header">
      <Link className="brand" to="/">
        <RefreshCcw size={22} />
        <span>U-Swap</span>
      </Link>
      <nav className="nav-links" aria-label="Principal">
        <NavLink to="/">
          <Search size={17} />
          Catalogo
        </NavLink>
        <NavLink to="/publish">
          <Plus size={17} />
          Publicar
        </NavLink>
        {user && (
          <NavLink to="/mis-publicaciones">
            <LayoutList size={17} />
            Mis publicaciones
          </NavLink>
        )}
        <NavLink to="/matches">
          <BookOpen size={17} />
          Solicitudes
          {pendingMatches > 0 && (
            <span className="nav-badge" title={`${pendingMatches} solicitud(es) pendiente(s)`}>
              <AlertCircle size={20} />
            </span>
          )}
        </NavLink>
        {user?.role === "ADMIN" && (
          <NavLink to="/admin">
            <Shield size={17} />
            Admin
          </NavLink>
        )}
      </nav>
      <div className="session">
        {user ? (
          <>
            <span>{user.name}</span>
            <button className="icon-button" onClick={onLogout} title="Cerrar sesion">
              <LogOut size={18} />
            </button>
          </>
        ) : (
          <NavLink className="login-link" to="/auth">
            Entrar
          </NavLink>
        )}
      </div>
    </header>
  );
}
