"""
AI Lead Intelligence API.

Endpoints:
  GET  /contacts/{id}/intelligence         — stream lead analysis via SSE
  GET  /contacts/{id}/intelligence/sync    — non-streaming version (cacheable)
  POST /leads/search                       — natural language query → filtered leads
"""
from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AnalystRequired, CurrentUser, ViewerRequired
from app.config import get_settings
from app.database import get_db
from app.models.contact import Contact, ContactFeature
from app.models.company import Company
from app.models.scoring import LeadScore
from app.schemas.common import OrmBase
from app.schemas.scoring import RankedLeadRead
from app.services.ai_intelligence import (
    get_lead_intelligence,
    natural_language_search,
    stream_lead_intelligence,
)

router = APIRouter()
logger = structlog.get_logger(__name__)
settings = get_settings()


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
    features = db.scalar(
        select(ContactFeature).where(ContactFeature.contact_id == contact_id)
    )
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
async def stream_intelligence(
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
async def get_intelligence_sync(
    contact_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Non-streaming intelligence report. Response cached 6 hours in Redis (if available)."""
    api_key = _get_api_key()

    # Try Redis cache first
    cache_key = f"intelligence:{contact_id}"
    try:
        import redis
        r = redis.from_url(settings.redis_url)
        cached = r.get(cache_key)
        if cached:
            import json
            return json.loads(cached)
    except Exception:
        pass

    contact_dict, features_dict, score_dict = _fetch_lead_context(contact_id, db)
    result = await get_lead_intelligence(
        contact=contact_dict,
        features=features_dict,
        latest_score=score_dict,
        api_key=api_key,
    )

    # Cache for 6 hours
    try:
        import redis, json
        r = redis.from_url(settings.redis_url)
        r.setex(cache_key, 21600, json.dumps(result))
    except Exception:
        pass

    return result


class NLSearchRequest(OrmBase):
    query: str
    page: int = 1
    page_size: int = 50


@router.post("/leads/search", dependencies=[ViewerRequired])
async def natural_language_leads_search(
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
    parsed = await natural_language_search(body.query, api_key)
    filters = parsed.get("filters", {})

    # Build query from parsed filters
    from sqlalchemy import func, text
    from app.schemas.scoring import RankedLeadRead

    latest = (
        select(LeadScore.contact_id, func.max(LeadScore.scored_at).label("max_scored_at"))
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
        q = q.where(Company.industry.ilike(f"%{filters['industry_contains']}%"))
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
