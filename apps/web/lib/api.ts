import { ApiError, errorMessage } from "@/lib/errors";
import { goToLogin } from "@/lib/navigation";
import type {
  Company,
  PaginatedResponse,
  RankedLead,
  ScoreSimulateRequest,
  ScoreSimulateResponse,
  ScoringRun,
} from "./types";

export { ApiError };

/**
 * Calls the API from the browser, through this app's own /bff proxy: same origin, with the session in httpOnly cookies. The page's JavaScript never sees a
 * token. A 401 means the session is over, so the user is sent to sign in again.
 */
export async function fetchApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  let res: Response;
  try {
    res = await fetch(`/bff${path}`, { ...init, headers, credentials: "same-origin", cache: "no-store" });
  } catch {
    throw new ApiError(0, "Could not reach the server. Check your connection.");
  }

  if (res.status === 401 && typeof window !== "undefined") {
    goToLogin();
    throw new ApiError(401, "Your session has expired. Sign in again.");
  }
  if (!res.ok) {
    const body: unknown = await res.json().catch(() => null);
    throw new ApiError(res.status, errorMessage(body, res.statusText || "Request failed"));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function signOut(): Promise<void> {
  await fetch("/session/logout", { method: "POST", credentials: "same-origin" });
}

// ---- Leads ----
export async function getLeads(params: {
  page?: number;
  page_size?: number;
  priority_tier?: string;
  min_score?: number;
  company_id?: string;
}): Promise<PaginatedResponse<RankedLead>> {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.page_size) q.set("page_size", String(params.page_size));
  if (params.priority_tier) q.set("priority_tier", params.priority_tier);
  if (params.min_score != null) q.set("min_score", String(params.min_score));
  if (params.company_id) q.set("company_id", params.company_id);
  return fetchApi(`/scoring/leads?${q}`);
}

// ---- Companies ----
export async function getCompanies(params: {
  page?: number;
  page_size?: number;
  size_tier?: string;
  search?: string;
}): Promise<PaginatedResponse<Company>> {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.page_size) q.set("page_size", String(params.page_size));
  if (params.size_tier) q.set("size_tier", params.size_tier);
  if (params.search) q.set("search", params.search);
  return fetchApi(`/companies?${q}`);
}

// ---- Scoring runs ----
export async function getScoringRuns(limit = 20): Promise<ScoringRun[]> {
  return fetchApi(`/scoring/runs?limit=${limit}`);
}

export async function triggerScoringRun(opts?: { filter_segment?: string; is_shadow?: boolean }): Promise<ScoringRun> {
  return fetchApi("/scoring/runs", { method: "POST", body: JSON.stringify(opts ?? {}) });
}

export async function getRun(id: string): Promise<ScoringRun> {
  return fetchApi(`/scoring/runs/${encodeURIComponent(id)}`);
}

// ---- Score simulation ----
export async function simulateScore(req: ScoreSimulateRequest): Promise<ScoreSimulateResponse> {
  return fetchApi("/scoring/simulate", { method: "POST", body: JSON.stringify(req) });
}
