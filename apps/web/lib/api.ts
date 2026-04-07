import type {
  Company,
  DashboardStats,
  PaginatedResponse,
  RankedLead,
  ScoreSimulateRequest,
  ScoreSimulateResponse,
  ScoringRun,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetchApi<T>(path: string, init?: RequestInit): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}/api/v1${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

// ---- Auth ----
export async function login(email: string, password: string) {
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new ApiError(res.status, "Invalid credentials");
  return res.json();
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

export async function triggerScoringRun(opts?: {
  filter_segment?: string;
  is_shadow?: boolean;
}): Promise<ScoringRun> {
  return fetchApi("/scoring/runs", {
    method: "POST",
    body: JSON.stringify(opts ?? {}),
  });
}

export async function getRun(id: string): Promise<ScoringRun> {
  return fetchApi(`/scoring/runs/${id}`);
}

// ---- Score simulation ----
export async function simulateScore(req: ScoreSimulateRequest): Promise<ScoreSimulateResponse> {
  return fetchApi("/scoring/simulate", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

// ---- Health ----
export async function getHealth() {
  const res = await fetch(`${API_BASE}/health`);
  return res.json();
}
