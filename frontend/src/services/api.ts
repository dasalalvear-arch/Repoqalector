import axios from "axios";

export type RepoSummary = {
  repo: string;
  chunks: number;
};

/** Un fragmento recuperado. `distance`: 0 = identico, 2 = opuesto. */
export type SearchHit = {
  file_path: string;
  line_start: number;
  line_end: number;
  content: string;
  distance: number;
};

/** Una entrada del historial. `hits` solo viene en las del asistente. */
export type Turn = {
  role: "user" | "assistant";
  content: string;
  hits?: SearchHit[];
};

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
});
