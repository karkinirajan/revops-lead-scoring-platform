"""
System configuration, as the settings page shows it.

  GET /system/config — the values that are safe to display; for each secret, only whether it is set
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.auth.dependencies import ViewerRequired
from app.config import get_settings

router = APIRouter()


class SystemConfig(BaseModel):
    hubspot_access_token_set: bool
    hubspot_portal_id_set: bool
    hubspot_webhook_secret_set: bool
    hubspot_batch_size: int
    hubspot_rate_limit_per_second: int
    anthropic_api_key_set: bool
    ai_model: str
    ai_cache_ttl_seconds: int
    ai_rate_limit_per_minute: int
    scoring_hot_threshold: int
    scoring_warm_threshold: int
    scoring_cool_threshold: int


@router.get("/config", response_model=SystemConfig, dependencies=[ViewerRequired])
def system_config() -> SystemConfig:
    s = get_settings()
    return SystemConfig(
        hubspot_access_token_set=bool(s.hubspot_access_token),
        hubspot_portal_id_set=bool(s.hubspot_portal_id),
        hubspot_webhook_secret_set=bool(s.hubspot_webhook_secret),
        hubspot_batch_size=s.hubspot_batch_size,
        hubspot_rate_limit_per_second=s.hubspot_rate_limit_per_second,
        anthropic_api_key_set=bool(s.anthropic_api_key),
        ai_model=s.ai_model,
        ai_cache_ttl_seconds=s.ai_intelligence_cache_ttl_seconds,
        ai_rate_limit_per_minute=s.ai_intelligence_rate_limit_per_minute,
        scoring_hot_threshold=s.scoring_hot_threshold,
        scoring_warm_threshold=s.scoring_warm_threshold,
        scoring_cool_threshold=s.scoring_cool_threshold,
    )
