import { Navigate, Route, Routes } from "react-router-dom";

import { Header } from "../components/Header";
import { useAuth } from "../hooks/useAuth";
import { usePendingMatches } from "../hooks/usePendingMatches";
import { AdminPage } from "../pages/AdminPage";
import { AuthPage } from "../pages/AuthPage";
import { CatalogPage } from "../pages/CatalogPage";
import { MatchesPage } from "../pages/MatchesPage";
import { MyPublicationsPage } from "../pages/MyPublicationsPage";
import { PublishPage } from "../pages/PublishPage";

export function App() {
  const auth = useAuth();
  const pendingMatches = usePendingMatches(auth.user);

  return (
    <div className="app-shell">
      <Header user={auth.user} onLogout={auth.logout} pendingMatches={pendingMatches} />
      <main>
        <Routes>
          <Route path="/" element={<CatalogPage user={auth.user} />} />
          <Route
            path="/auth"
            element={auth.user || auth.token ? <Navigate to="/" replace /> : <AuthPage auth={auth} />}
          />
          <Route
            path="/publish"
            element={auth.user ? <PublishPage /> : <Navigate to="/auth" replace />}
          />
          <Route
            path="/publish/:id"
            element={auth.user ? <PublishPage /> : <Navigate to="/auth" replace />}
          />
          <Route
            path="/matches"
            element={auth.user ? <MatchesPage user={auth.user} /> : <Navigate to="/auth" replace />}
          />
          <Route
            path="/mis-publicaciones"
            element={auth.user ? <MyPublicationsPage user={auth.user} /> : <Navigate to="/auth" replace />}
          />
          {/* Panel Admin: solo ADMIN, los STUDENT son redirigidos */}
          <Route
            path="/admin"
            element={
              !auth.user
                ? <Navigate to="/auth" replace />
                : auth.user.role === "ADMIN"
                  ? <AdminPage user={auth.user} />
                  : <Navigate to="/" replace />
            }
          />
        </Routes>
      </main>
    </div>
  );
} 