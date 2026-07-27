import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

// Deriva el origen de la API (ej: https://api.uswap.cl) desde VITE_API_URL
// para autorizarlo en connect-src sin abrir la politica a todo internet.
function apiOrigin(apiUrl: string | undefined): string {
  if (!apiUrl) return "";
  try {
    return new URL(apiUrl).origin;
  } catch {
    return "";
  }
}

// Inyecta la Content-Security-Policy solo en el build de produccion.
// En dev no se aplica: Vite usa scripts inline para HMR y una CSP estricta
// (script-src 'self') romperia el hot reload.
function cspPlugin(apiUrl: string | undefined): Plugin {
  const connect = ["'self'", "https:", apiOrigin(apiUrl)].filter(Boolean).join(" ");
  const csp = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' https: blob:",
    "font-src 'self'",
    `connect-src ${connect}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "manifest-src 'self'",
    "worker-src 'self'",
  ].join("; ");

  return {
    name: "uswap-csp",
    apply: "build",
    transformIndexHtml(html) {
      return {
        html,
        tags: [
          {
            tag: "meta",
            attrs: {
              "http-equiv": "Content-Security-Policy",
              content: csp,
            },
            injectTo: "head-prepend",
          },
        ],
      };
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react(), cspPlugin(env.VITE_API_URL)],
    server: {
      port: 5173,
    },
  };
});
