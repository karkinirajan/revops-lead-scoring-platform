/** The API as the web *server* reaches it (inside docker compose: http://api:8000). Browsers never call it directly: they go through /bff. */
export function apiBase(): string {
  return (process.env.API_INTERNAL_URL || "http://localhost:8000").replace(/\/+$/, "");
}

export const ACCESS_COOKIE = "rv_access";
export const REFRESH_COOKIE = "rv_refresh";
