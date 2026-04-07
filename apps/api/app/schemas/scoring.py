from datetime import datetime

from app.schemas.common import OrmBase


class LeadScoreRead(OrmBase):
    id: str
    contact_id: str
    company_id: str | None
    lead_score: int
    priority_tier: str
    model_version: str
    score_reason: str | None
    feature_contributions: dict | None
    recommended_action: str | None
    is_shadow: bool
    scored_at: datetime
    feature_freshness_at: datetime | None
    synced_to_hubspot_at: datetime | None


class ScoringRunCreate(OrmBase):
    filter_segment: str | None = None
    is_shadow: bool = False


class ScoringRunRead(OrmBase):
    id: str
    model_version: str
    status: str
    filter_segment: str | None
    is_shadow: bool
    triggered_by: str | None
    total_contacts: int
    scored_count: int
    error_count: int
    started_at: datetime
    completed_at: datetime | None
    duration_seconds: float | None
    error_detail: str | None


class ScoreSimulateRequest(OrmBase):
    api_calls_7d: int = 0
    api_calls_30d: int = 0
    page_views_7d: int = 0
    pricing_page_visited: bool = False
    email_opens_7d: int = 0
    email_clicks_7d: int = 0
    demo_requested: bool = False
    free_trial_active: bool = False
    integration_connected: bool = False
    integrations_count: int = 0
    days_since_last_activity: int = 999
    company_size_tier: str = "unknown"


class ScoreSimulateResponse(OrmBase):
    lead_score: int
    priority_tier: str
    score_reason: str
    feature_contributions: dict
    model_version: str


class RankedLeadRead(OrmBase):
    """Joined view: contact + latest score for the leads table."""

    contact_id: str
    email: str
    full_name: str
    job_title: str | None
    company_id: str | None
    company_name: str | None
    company_size_tier: str | None
    lead_score: int
    priority_tier: str
    score_reason: str | None
    recommended_action: str | None
    model_version: str
    scored_at: datetime
    synced_to_hubspot_at: datetime | None
