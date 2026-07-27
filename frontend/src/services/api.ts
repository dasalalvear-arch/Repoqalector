import axios from "axios";

export type Source = {
  file_path: string;
  line_start: number;
  line_end: number;
};

export type Answer = {
  answer: string;
  sources: Source[];
};

/** Una entrada del historial. `sources` solo viene en las del asistente. */
export type Turn = {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
};

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
});
