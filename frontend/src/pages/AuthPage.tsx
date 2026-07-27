import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

type AuthPageProps = {
  auth: {
    login: (email: string, password: string) => Promise<string>;  // cambiar void → string
    register: (name: string, email: string, password: string, career: string) => Promise<void>;
  };
};

export function AuthPage({ auth }: AuthPageProps) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email"));
    const password = String(form.get("password"));

    try {
      if (mode === "register") {
        await auth.register(String(form.get("name")), email, password, String(form.get("career") ?? ""));
        navigate("/", { replace: true });
      } else {
        const role = await auth.login(email, password);
        console.log("role recibido:", role);
        navigate(role === "ADMIN" ? "/admin" : "/", { replace: true });
      }
    } catch {
      setError("Revisa tus datos. Recuerda usar tu correo @utem.cl.");
    }
  }

  return (
    <section className="auth-layout">
      <div className="auth-panel">
        <div className="segmented">
          <button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>
            Login
          </button>
          <button
            className={mode === "register" ? "active" : ""}
            onClick={() => setMode("register")}
          >
            Registro
          </button>
        </div>
        <form onSubmit={handleSubmit} className="form-stack">
          {mode === "register" && (
            <>
              <label>
                Nombre
                <input name="name" required minLength={2} />
              </label>
              <label>
                Carrera
                <input name="career" />
              </label>
            </>
          )}
          <label>
            Correo UTEM
            <input name="email" type="email" required placeholder="nombre@utem.cl" />
          </label>
          <label>
            Contrasena
            <input name="password" type="password" required minLength={8} />
          </label>
          {error && <p className="form-error">{error}</p>}
          <button className="primary-button" type="submit">
            {mode === "register" ? "Crear cuenta" : "Entrar"}
          </button>
        </form>
      </div>
    </section>
  );
}
