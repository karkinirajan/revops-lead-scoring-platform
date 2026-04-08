from datetime import datetime

from pydantic import Field

from app.schemas.common import OrmBase


class ConversionCreate(OrmBase):
    contact_id: str
    converted_at: datetime
    deal_value: float | None = None
    days_to_close: int | None = None
    plan_tier: str | None = None
    source: str = "manual"
    crm_deal_id: str | None = None
    notes: str | None = None


class ConversionRead(OrmBase):
    id: str
    contact_id: str
    converted_at: datetime
    deal_value: float | None
    days_to_close: int | None
    plan_tier: str | None
    score_at_conversion: int | None
    tier_at_conversion: str | None
    model_version_at_conversion: str | None
    source: str
    crm_deal_id: str | None
    created_at: datetime


class TierAccuracy(OrmBase):
    tier: str
    total_leads: int
    converted: int
    precision: float          # converted / total_leads in this tier
    avg_score: float
    avg_deal_value: float | None
    avg_days_to_close: float | None


class ModelAccuracyReport(OrmBase):
    model_version: str
    total_scored: int
    total_converted: int
    overall_conversion_rate: float
    tiers: list[TierAccuracy]
    generated_at: datetime


class HubSpotDealWebhook(OrmBase):
    """Shape of a HubSpot deal-won webhook payload."""
    objectId: str = Field(..., description="HubSpot deal ID")
    propertyName: str | None = None
    propertyValue: str | None = None
    # full properties map
    properties: dict | None = None
