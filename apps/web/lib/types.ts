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

export interface Conversion {
  id: string;
  contact_id: string;
  converted_at: string;
  deal_value: number | null;
  days_to_close: number | null;
  plan_tier: string | null;
  score_at_conversion: number | null;
  tier_at_conversion: PriorityTier | null;
  model_version_at_conversion: string | null;
  source: string;
  crm_deal_id: string | null;
  created_at: string;
}

export interface TierAccuracy {
  tier: PriorityTier;
  total_leads: number;
  converted: number;
  precision: number;
  avg_score: number;
  avg_deal_value: number | null;
  avg_days_to_close: number | null;
}

export interface ModelAccuracyReport {
  model_version: string;
  total_scored: number;
  total_converted: number;
  overall_conversion_rate: number;
  tiers: TierAccuracy[];
  generated_at: string;
}

export interface Webhook {
  id: string;
  name: string;
  url: string;
  events: string;
  tier_filter: string | null;
  status: "active" | "paused" | "disabled";
  total_deliveries: number;
  successful_deliveries: number;
  failed_deliveries: number;
  last_triggered_at: string | null;
  created_at: string;
}

export interface CrmConnection {
  id: string;
  crm_type: "hubspot" | "salesforce";
  name: string;
  org_id: string | null;
  instance_url: string | null;
  is_active: boolean;
  sync_direction: string;
  last_inbound_sync_at: string | null;
  last_outbound_sync_at: string | null;
  last_sync_error: string | null;
  total_records_synced: number;
  created_at: string;
}

export interface ModelRegistryEntry {
  id: string;
  version: string;
  algorithm: string;
  stage: "training" | "shadow" | "champion" | "archived";
  training_rows: number | null;
  positive_rate: number | null;
  precision_hot: number | null;
  recall_hot: number | null;
  roc_auc: number | null;
  f1_score: number | null;
  feature_importances: Record<string, number> | null;
  trained_by: string | null;
  trained_at: string | null;
  promoted_at: string | null;
  created_at: string;
}

// ---- Analytics ----
export interface TierAccuracy {
  tier: PriorityTier;
  total_leads: number;
  converted: number;
  precision: number;
  avg_score: number;
  avg_deal_value: number | null;
  avg_days_to_close: number | null;
}

export interface ModelAccuracy {
  model_version: string;
  total_scored: number;
  total_converted: number;
  overall_conversion_rate: number;
  tiers: TierAccuracy[];
  generated_at: string;
}

export interface ScoreDistribution {
  buckets: { range: string; count: number }[];
  total: number;
}

export interface Conversion {
  id: string;
  contact_id: string;
  converted_at: string;
  deal_value: number | null;
  days_to_close: number | null;
  plan_tier: string | null;
  score_at_conversion: number | null;
  tier_at_conversion: PriorityTier | null;
  model_version_at_conversion: string | null;
  source: string;
  crm_deal_id: string | null;
}

export type ConversionList = PaginatedResponse<Conversion>;

/** What the server reports about its own configuration: values that are safe to show, and for each secret only whether it is set. */
export interface SystemConfig {
  hubspot_access_token_set: boolean;
  hubspot_portal_id_set: boolean;
  hubspot_webhook_secret_set: boolean;
  hubspot_batch_size: number;
  hubspot_rate_limit_per_second: number;
  anthropic_api_key_set: boolean;
  ai_model: string;
  ai_cache_ttl_seconds: number;
  ai_rate_limit_per_minute: number;
  scoring_hot_threshold: number;
  scoring_warm_threshold: number;
  scoring_cool_threshold: number;
}
