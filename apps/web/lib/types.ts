export type PriorityTier = "HOT" | "WARM" | "COOL" | "COLD";

export interface RankedLead {
  contact_id: string;
  email: string;
  full_name: string;
  job_title: string | null;
  company_id: string | null;
  company_name: string | null;
  company_size_tier: string | null;
  lead_score: number;
  priority_tier: PriorityTier;
  score_reason: string | null;
  recommended_action: string | null;
  model_version: string;
  scored_at: string;
  synced_to_hubspot_at: string | null;
}

export interface Company {
  id: string;
  name: string;
  domain: string | null;
  industry: string | null;
  employee_count: number | null;
  size_tier: string | null;
  source_system: string;
  created_at: string;
  updated_at: string;
}

export interface ScoringRun {
  id: string;
  model_version: string;
  status: "pending" | "running" | "completed" | "failed" | "partial";
  filter_segment: string | null;
  is_shadow: boolean;
  triggered_by: string | null;
  total_contacts: number;
  scored_count: number;
  error_count: number;
  started_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
  error_detail: string | null;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface DashboardStats {
  total_leads_scored: number;
  hot_leads: number;
  warm_leads: number;
  sync_success_rate: number;
  last_run_at: string | null;
  last_run_duration: number | null;
}

export interface ScoreSimulateRequest {
  api_calls_7d: number;
  api_calls_30d: number;
  page_views_7d: number;
  pricing_page_visited: boolean;
  email_opens_7d: number;
  email_clicks_7d: number;
  demo_requested: boolean;
  free_trial_active: boolean;
  integration_connected: boolean;
  integrations_count: number;
  days_since_last_activity: number;
  company_size_tier: string;
}

export interface ScoreSimulateResponse {
  lead_score: number;
  priority_tier: PriorityTier;
  score_reason: string;
  feature_contributions: Record<string, number>;
  model_version: string;
}
