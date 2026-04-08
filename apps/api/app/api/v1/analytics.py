"""
Analytics API — conversion tracking and model accuracy reporting.

Endpoints:
  POST /analytics/conversions              — record a manual conversion
  GET  /analytics/conversions              — list conversions
  POST /analytics/conversions/hubspot      — HubSpot deal-won webhook receiver
  GET  /analytics/model-accuracy           — precision/recall per tier
  GET  /analytics/score-distribution       — histogram of score buckets
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth.dependencies import AnalystRequired, ViewerRequired
from app.config import get_settings
from app.database import get_db
from app.models.contact import Contact
from app.models.conversion import Conversion
from app.models.scoring import LeadScore
from app.schemas.common import PaginatedResponse
from app.schemas.conversion import (
    ConversionCreate,
    ConversionRead,
    HubSpotDealWebhook,
    ModelAccuracyReport,
    TierAccuracy,
)

router = APIRouter()
logger = structlog.get_logger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Conversion CRUD
# ---------------------------------------------------------------------------

@router.post("/conversions", response_model=ConversionRead, status_code=status.HTTP_201_CREATED,
             dependencies=[AnalystRequired])
def record_conversion(body: ConversionCreate, db: Annotated[Session, Depends(get_db)]):
    """Record a deal-won conversion for a contact."""
    contact = db.get(Contact, body.contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Attach latest score snapshot
    latest_score = db.scalar(
        select(LeadScore)
        .where(LeadScore.contact_id == body.contact_id, LeadScore.is_shadow == False)  # noqa: E712
        .order_by(LeadScore.scored_at.desc())
        .limit(1)
    )

    conversion = Conversion(
        contact_id=body.contact_id,
        converted_at=body.converted_at,
        deal_value=body.deal_value,
        days_to_close=body.days_to_close,
        plan_tier=body.plan_tier,
        source=body.source,
        crm_deal_id=body.crm_deal_id,
        notes=body.notes,
        score_at_conversion=latest_score.lead_score if latest_score else None,
        tier_at_conversion=latest_score.priority_tier if latest_score else None,
        model_version_at_conversion=latest_score.model_version if latest_score else None,
    )
    db.add(conversion)
    db.commit()
    db.refresh(conversion)
    logger.info("conversion_recorded", contact_id=body.contact_id, deal_value=body.deal_value)
    return conversion


@router.get("/conversions", response_model=PaginatedResponse[ConversionRead], dependencies=[ViewerRequired])
def list_conversions(
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    tier: str | None = Query(None, description="Filter by tier_at_conversion"),
):
    q = select(Conversion).order_by(Conversion.converted_at.desc())
    if tier:
        q = q.where(Conversion.tier_at_conversion == tier.upper())

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = db.scalars(q.offset((page - 1) * page_size).limit(page_size)).all()
    return PaginatedResponse(
        items=list(items),
        total=total or 0,
        page=page,
        page_size=page_size,
        pages=max(1, -(-(total or 0) // page_size)),
    )


# ---------------------------------------------------------------------------
# HubSpot deal-won webhook receiver
# ---------------------------------------------------------------------------

@router.post("/conversions/hubspot", status_code=status.HTTP_200_OK)
async def hubspot_deal_webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_hubspot_signature: str | None = Header(None),
):
    """
    Receive HubSpot deal-won webhook.
    Configure in HubSpot: Workflows → Webhook action → this URL.
    Verifies HMAC signature when HUBSPOT_WEBHOOK_SECRET is set.
    """
    raw_body = await request.body()

    # Optional signature verification
    webhook_secret = getattr(settings, "hubspot_webhook_secret", "")
    if webhook_secret and x_hubspot_signature:
        expected = hmac.new(
            webhook_secret.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, x_hubspot_signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    import json
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # HubSpot sends a list of events
    events = payload if isinstance(payload, list) else [payload]
    created = 0

    for event in events:
        props = event.get("properties", {})
        hs_deal_id = str(event.get("objectId", event.get("id", "")))
        email = (props.get("email") or {}).get("value", "")

        if not email:
            continue

        contact = db.scalar(select(Contact).where(Contact.email == email.lower()))
        if not contact:
            logger.warning("hubspot_webhook_contact_not_found", email=email)
            continue

        # Skip duplicates
        existing = db.scalar(select(Conversion).where(Conversion.crm_deal_id == hs_deal_id))
        if existing:
            continue

        deal_value_str = (props.get("amount") or {}).get("value", "0")
        try:
            deal_value = float(deal_value_str)
        except (TypeError, ValueError):
            deal_value = None

        latest_score = db.scalar(
            select(LeadScore)
            .where(LeadScore.contact_id == contact.id, LeadScore.is_shadow == False)  # noqa: E712
            .order_by(LeadScore.scored_at.desc())
            .limit(1)
        )

        conversion = Conversion(
            contact_id=contact.id,
            converted_at=datetime.now(timezone.utc),
            deal_value=deal_value,
            source="hubspot_webhook",
            crm_deal_id=hs_deal_id,
            score_at_conversion=latest_score.lead_score if latest_score else None,
            tier_at_conversion=latest_score.priority_tier if latest_score else None,
            model_version_at_conversion=latest_score.model_version if latest_score else None,
        )
        db.add(conversion)
        created += 1

    db.commit()
    logger.info("hubspot_webhook_processed", events=len(events), created=created)
    return {"status": "ok", "created": created}


# ---------------------------------------------------------------------------
# Model accuracy report
# ---------------------------------------------------------------------------

@router.get("/model-accuracy", response_model=ModelAccuracyReport, dependencies=[ViewerRequired])
def model_accuracy(
    db: Annotated[Session, Depends(get_db)],
    model_version: str | None = Query(None, description="Filter to a specific model version"),
):
    """
    Returns precision/recall per priority tier.

    Precision per tier = (leads in tier that converted) / (total leads in tier)
    Uses the tier_at_conversion captured at deal-close time.
    """
    mv_filter = f"AND model_version_at_conversion = :mv" if model_version else ""
    mv_params: dict = {"mv": model_version} if model_version else {}

    # Tier breakdown from conversions
    tier_rows = db.execute(
        text(f"""
            SELECT
                tier_at_conversion,
                COUNT(*) AS converted,
                AVG(score_at_conversion) AS avg_score,
                AVG(deal_value) AS avg_deal_value,
                AVG(days_to_close) AS avg_days_to_close
            FROM conversions
            WHERE tier_at_conversion IS NOT NULL
              {mv_filter}
            GROUP BY tier_at_conversion
        """),
        mv_params,
    ).fetchall()

    # Total scored per tier (denominator for precision)
    scored_query = text(f"""
        SELECT priority_tier, COUNT(DISTINCT contact_id) AS total
        FROM lead_scores
        WHERE is_shadow = false
          {"AND model_version = :mv" if model_version else ""}
        GROUP BY priority_tier
    """)
    scored_rows = db.execute(scored_query, mv_params if model_version else {}).fetchall()
    scored_by_tier = {r[0]: r[1] for r in scored_rows}

    total_scored = sum(scored_by_tier.values())
    total_converted = sum(r[1] for r in tier_rows)
    overall_rate = round(total_converted / total_scored, 4) if total_scored > 0 else 0.0

    tiers = []
    for row in tier_rows:
        tier_name = row[0]
        converted = row[1]
        total_in_tier = scored_by_tier.get(tier_name, 0)
        precision = round(converted / total_in_tier, 4) if total_in_tier > 0 else 0.0
        tiers.append(TierAccuracy(
            tier=tier_name,
            total_leads=total_in_tier,
            converted=converted,
            precision=precision,
            avg_score=round(float(row[2] or 0), 1),
            avg_deal_value=round(float(row[3]), 2) if row[3] else None,
            avg_days_to_close=round(float(row[4]), 1) if row[4] else None,
        ))

    # Sort by tier order
    tier_order = {"HOT": 0, "WARM": 1, "COOL": 2, "COLD": 3}
    tiers.sort(key=lambda t: tier_order.get(t.tier, 99))

    used_version = model_version or "all"
    return ModelAccuracyReport(
        model_version=used_version,
        total_scored=total_scored,
        total_converted=total_converted,
        overall_conversion_rate=overall_rate,
        tiers=tiers,
        generated_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Score distribution histogram
# ---------------------------------------------------------------------------

@router.get("/score-distribution", dependencies=[ViewerRequired])
def score_distribution(
    db: Annotated[Session, Depends(get_db)],
    buckets: int = Query(10, ge=5, le=20),
):
    """Return a histogram of lead scores in equal-width buckets."""
    rows = db.execute(
        text("""
            SELECT lead_score
            FROM lead_scores ls
            INNER JOIN (
                SELECT contact_id, MAX(scored_at) AS max_sa
                FROM lead_scores
                WHERE is_shadow = false
                GROUP BY contact_id
            ) latest ON ls.contact_id = latest.contact_id AND ls.scored_at = latest.max_sa
        """)
    ).fetchall()

    scores = [r[0] for r in rows]
    if not scores:
        return {"buckets": [], "total": 0}

    bucket_size = 100 // buckets
    histogram = [{"range": f"{i*bucket_size}-{(i+1)*bucket_size-1}", "count": 0} for i in range(buckets)]
    for s in scores:
        idx = min(s // bucket_size, buckets - 1)
        histogram[idx]["count"] += 1

    return {"buckets": histogram, "total": len(scores)}
