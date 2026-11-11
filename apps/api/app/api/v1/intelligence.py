"""
AI Lead Intelligence API.

Endpoints:
  GET  /contacts/{id}/intelligence         — stream lead analysis via SSE
  GET  /contacts/{id}/intelligence/sync    — non-streaming version (cacheable)
  POST /leads/search                       — natural language query → filtered leads
"""

from __future__ import annotations

import contextlib
import json
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import ViewerRequired
from app.config import get_settings
from app.database import get_db
from app.middleware.rate_limit import limiter
from app.models.company import Company
from app.models.contact import Contact, ContactFeature
from app.models.scoring import LeadScore
from app.schemas.common import OrmBase
from app.schemas.scoring import RankedLeadRead
from app.services.ai_intelligence import (
    GENERIC_ERROR,
    get_lead_intelligence,
    natural_language_search,
    stream_lead_intelligence,
)
from app.services.search_utils import LIKE_ESCAPE, contains_pattern

router = APIRouter()
logger = structlog.get_logger(__name__)
settings = get_settings()

AI_LIMIT = (
    f"{settings.ai_intelligence_rate_limit_per_minute}/minute"  # each call is paid for: limited per client address
)
CACHE_SECONDS = settings.ai_intelligence_cache_ttl_seconds


def _cache():
    """A Redis client for the report cache. Short timeouts: a dead Redis must not slow requests (callers treat any error as a cache miss)."""
    import redis

    return redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)


def _get_api_key() -> str:
    key = getattr(settings, "anthropic_api_key", "") or ""
    if not key:
        raise HTTPException(
            status_code=503,
            detail="AI intelligence not configured. Set ANTHROPIC_API_KEY environment variable.",
        )
    return key


def _fetch_lead_context(contact_id: str, db: Session) -> tuple[dict, dict, dict]:
    """Fetch contact, features, and latest score as plain dicts."""
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    company = db.get(Company, contact.company_id) if contact.company_id else None
    features = db.scalar(select(ContactFeature).where(ContactFeature.contact_id == contact_id))
    latest_score = db.scalar(
        select(LeadScore)
        .where(LeadScore.contact_id == contact_id, LeadScore.is_shadow == False)  # noqa: E712
        .order_by(LeadScore.scored_at.desc())
        .limit(1)
    )

    contact_dict = {
        "id": contact.id,
        "email": contact.email,
        "full_name": contact.full_name,
        "job_title": contact.job_title,
        "company_name": company.name if company else None,
        "company_size_tier": company.size_tier if company else "unknown",
    }
    features_dict = {}
    if features:
        features_dict = {
            "api_calls_7d": features.api_calls_7d,
            "api_calls_30d": features.api_calls_30d,
            "page_views_7d": features.page_views_7d,
            "pricing_page_visited": features.pricing_page_visited,
            "email_opens_7d": features.email_opens_7d,
            "email_clicks_7d": features.email_clicks_7d,
            "docs_page_visits_7d": features.docs_page_visits_7d,
            "demo_requested": features.demo_requested,
            "free_trial_active": features.free_trial_active,
            "integration_connected": features.integration_connected,
            "integrations_count": features.integrations_count,
            "sessions_7d": features.sessions_7d,
            "days_since_last_activity": features.days_since_last_activity,
        }
    score_dict = {}
    if latest_score:
        score_dict = {
            "lead_score": latest_score.lead_score,
            "priority_tier": latest_score.priority_tier,
            "score_reason": latest_score.score_reason,
            "feature_contributions": latest_score.feature_contributions,
            "scored_at": latest_score.scored_at.isoformat() if latest_score.scored_at else None,
        }

    return contact_dict, features_dict, score_dict


@router.get("/contacts/{contact_id}/intelligence", dependencies=[ViewerRequired])
@limiter.limit(AI_LIMIT)
async def stream_intelligence(
    request: Request,
    contact_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Stream an AI-generated lead intelligence report via SSE.
    Each chunk arrives as: data: {"chunk": "..."}\\n\\n
    Final message: data: [DONE]\\n\\n
    """
    api_key = _get_api_key()
    contact_dict, features_dict, score_dict = _fetch_lead_context(contact_id, db)

    async def event_generator():
        async for chunk in stream_lead_intelligence(
            contact=contact_dict,
            features=features_dict,
            latest_score=score_dict,
            api_key=api_key,
        ):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/contacts/{contact_id}/intelligence/sync", dependencies=[ViewerRequired])
@limiter.limit(AI_LIMIT)
async def get_intelligence_sync(
    request: Request,
    contact_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Non-streaming intelligence report. Response cached 6 hours in Redis (if available)."""
    api_key = _get_api_key()

    contact_dict, features_dict, score_dict = _fetch_lead_context(
        contact_id, db
    )  # 404 for an unknown contact before anything is cached or paid for

    cache_key = f"intelligence:{contact_id}"
    try:
        cached = _cache().get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    try:
        result = await get_lead_intelligence(
            contact=contact_dict,
            features=features_dict,
            latest_score=score_dict,
            api_key=api_key,
        )
    except Exception as exc:
        logger.error("ai_intelligence_failed", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail=GENERIC_ERROR) from None

    with contextlib.suppress(Exception):  # the cache is optional
        _cache().setex(cache_key, CACHE_SECONDS, json.dumps(result))

    return result


class NLSearchRequest(OrmBase):
    query: str = Field(min_length=1, max_length=500)
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=50, ge=1, le=200)


@router.post("/leads/search", dependencies=[ViewerRequired])
@limiter.limit(AI_LIMIT)
async def natural_language_leads_search(
    request: Request,
    body: NLSearchRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Natural language lead search.
    Parses the query with Claude, then applies the resulting filters to the leads table.

    Example: "HOT leads in fintech who visited pricing page but haven't requested a demo"
    """
    api_key = _get_api_key()

    # Parse NL query → structured filters
    try:
        parsed = await natural_language_search(body.query, api_key)
    except Exception as exc:
        logger.error("ai_search_failed", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail=GENERIC_ERROR) from None
    filters = parsed.get("filters", {})  # already validated: known fields, right types, in range

    # Build query from parsed filters
    from sqlalchemy import func

    # The latest *live* score per contact. A newer shadow score must not hide it: the shadow model scores alongside the live one, and the live rows are
    # the ones selected below.
    latest = (
        select(LeadScore.contact_id, func.max(LeadScore.scored_at).label("max_scored_at"))
        .where(LeadScore.is_shadow == False)  # noqa: E712
        .group_by(LeadScore.contact_id)
        .subquery()
    )
    q = (
        select(LeadScore, Contact, Company, ContactFeature)
        .join(latest, (LeadScore.contact_id == latest.c.contact_id) & (LeadScore.scored_at == latest.c.max_scored_at))
        .join(Contact, LeadScore.contact_id == Contact.id)
        .outerjoin(Company, Contact.company_id == Company.id)
        .outerjoin(ContactFeature, ContactFeature.contact_id == Contact.id)
        .where(LeadScore.is_shadow == False)  # noqa: E712
    )

    # Apply parsed filters
    if filters.get("tier"):
        tiers = [t.upper() for t in filters["tier"]]
        q = q.where(LeadScore.priority_tier.in_(tiers))
    if filters.get("min_score") is not None:
        q = q.where(LeadScore.lead_score >= filters["min_score"])
    if filters.get("max_score") is not None:
        q = q.where(LeadScore.lead_score <= filters["max_score"])
    if filters.get("company_size_tier"):
        q = q.where(Company.size_tier == filters["company_size_tier"])
    if filters.get("industry_contains"):
        q = q.where(Company.industry.ilike(contains_pattern(filters["industry_contains"]), escape=LIKE_ESCAPE))
    if filters.get("pricing_page_visited") is not None:
        q = q.where(ContactFeature.pricing_page_visited == filters["pricing_page_visited"])
    if filters.get("demo_requested") is not None:
        q = q.where(ContactFeature.demo_requested == filters["demo_requested"])
    if filters.get("free_trial_active") is not None:
        q = q.where(ContactFeature.free_trial_active == filters["free_trial_active"])
    if filters.get("integration_connected") is not None:
        q = q.where(ContactFeature.integration_connected == filters["integration_connected"])
    if filters.get("days_since_last_activity_max") is not None:
        q = q.where(ContactFeature.days_since_last_activity <= filters["days_since_last_activity_max"])
    if filters.get("api_calls_7d_min") is not None:
        q = q.where(ContactFeature.api_calls_7d >= filters["api_calls_7d_min"])
    if filters.get("email_clicks_7d_min") is not None:
        q = q.where(ContactFeature.email_clicks_7d >= filters["email_clicks_7d_min"])

    q = q.order_by(LeadScore.lead_score.desc())
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.execute(q.offset((body.page - 1) * body.page_size).limit(body.page_size)).all()

    items = [
        RankedLeadRead(
            contact_id=score.contact_id,
            email=contact.email,
            full_name=contact.full_name,
            job_title=contact.job_title,
            company_id=contact.company_id,
            company_name=company.name if company else None,
            company_size_tier=company.size_tier if company else None,
            lead_score=score.lead_score,
            priority_tier=score.priority_tier,
            score_reason=score.score_reason,
            recommended_action=score.recommended_action,
            model_version=score.model_version,
            scored_at=score.scored_at,
            synced_to_hubspot_at=score.synced_to_hubspot_at,
        )
        for score, contact, company, features in rows
    ]

    return {
        "query": body.query,
        "parsed_filters": filters,
        "total": total or 0,
        "page": body.page,
        "page_size": body.page_size,
        "results": [i.model_dump() for i in items],
    }
