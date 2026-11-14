import axios from "axios";

export type RepoSummary = {
  repo: string;
  chunks: number;
};

/** Un fragmento recuperado. `score`: mayor es mejor, en los tres modos. */
export type SearchHit = {
  file_path: string;
  line_start: number;
  line_end: number;
  content: string;
  score: number;
};

/** Respuesta de /ask. Si `found`, `[n]` en `answer` es `sources[n-1]`; si no, `sources` son los recuperados. */
export type AskResponse = {
  answer: string;
  found: boolean;
  sources: SearchHit[];
};

/** Una entrada del historial. `hits` y `found` solo vienen en las del asistente. */
export type Turn = {
  role: "user" | "assistant";
  content: string;
  found?: boolean;
  hits?: SearchHit[];
};

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
});
