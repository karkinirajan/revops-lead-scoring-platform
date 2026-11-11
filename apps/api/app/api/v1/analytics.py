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

import math
from datetime import UTC, datetime
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
    ModelAccuracyReport,
    TierAccuracy,
)
from app.security.hubspot import verify_v3
from app.services.webhook_service import notify_conversion

router = APIRouter()
logger = structlog.get_logger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Conversion CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/conversions", response_model=ConversionRead, status_code=status.HTTP_201_CREATED, dependencies=[AnalystRequired]
)
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
    notify_conversion(db, contact, conversion)
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


MAX_WEBHOOK_BODY_BYTES = 1_000_000
MAX_WEBHOOK_EVENTS = 1000


def _public_url(request: Request) -> str:
    base = settings.public_api_url.rstrip("/")
    if not base:
        return str(request.url)
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{base}{request.url.path}{query}"


def _property_value(props: object, name: str) -> object:
    """HubSpot sends properties as {"name": {"value": ...}}; anything else reads as missing."""
    entry = props.get(name) if isinstance(props, dict) else None
    return entry.get("value") if isinstance(entry, dict) else None


@router.post("/conversions/hubspot", status_code=status.HTTP_200_OK)
async def hubspot_deal_webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_hubspot_signature_v3: str | None = Header(None),
    x_hubspot_request_timestamp: str | None = Header(None),
):
    """
    Receive HubSpot deal-won webhook.
    Configure in HubSpot: Workflows → Webhook action → this URL.
    Every request must carry a valid HubSpot v3 signature (HUBSPOT_WEBHOOK_SECRET is the app's client secret); without the secret the endpoint is off.
    """
    webhook_secret = settings.hubspot_webhook_secret
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="HubSpot webhook not configured. Set HUBSPOT_WEBHOOK_SECRET.")

    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    if not verify_v3(
        secret=webhook_secret,
        method=request.method,
        url=_public_url(request),
        body=raw_body,
        timestamp=x_hubspot_request_timestamp or "",
        signature=x_hubspot_signature_v3 or "",
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    import json

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from None

    # HubSpot sends a list of events
    events = payload if isinstance(payload, list) else [payload]
    if len(events) > MAX_WEBHOOK_EVENTS:
        raise HTTPException(status_code=413, detail=f"At most {MAX_WEBHOOK_EVENTS} events per request")
    created = 0
    recorded: list[tuple[Contact, Conversion]] = []

    for event in events:
        if not isinstance(event, dict):
            continue
        props = event.get("properties", {})
        hs_deal_id = str(event.get("objectId", event.get("id", "")))
        email = _property_value(props, "email")

        if not hs_deal_id or not isinstance(email, str) or not email.strip():
            continue
        email = email.strip()

        contact = db.scalar(select(Contact).where(Contact.email == email.lower()))
        if not contact:
            logger.warning("hubspot_webhook_contact_not_found", email=email)
            continue

        # Skip duplicates
        existing = db.scalar(select(Conversion).where(Conversion.crm_deal_id == hs_deal_id))
        if existing:
            continue

        amount = _property_value(props, "amount") or 0
        try:
            deal_value = (
                float(amount) if isinstance(amount, int | float | str) and not isinstance(amount, bool) else None
            )
        except ValueError:
            deal_value = None
        if deal_value is not None and not math.isfinite(deal_value):
            deal_value = None

        latest_score = db.scalar(
            select(LeadScore)
            .where(LeadScore.contact_id == contact.id, LeadScore.is_shadow == False)  # noqa: E712
            .order_by(LeadScore.scored_at.desc())
            .limit(1)
        )

        conversion = Conversion(
            contact_id=contact.id,
            converted_at=datetime.now(UTC),
            deal_value=deal_value,
            source="hubspot_webhook",
            crm_deal_id=hs_deal_id,
            score_at_conversion=latest_score.lead_score if latest_score else None,
            tier_at_conversion=latest_score.priority_tier if latest_score else None,
            model_version_at_conversion=latest_score.model_version if latest_score else None,
        )
        db.add(conversion)
        recorded.append((contact, conversion))
        created += 1

    db.commit()
    for contact, conversion in recorded:
        notify_conversion(db, contact, conversion)
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
    mv_filter = "AND model_version_at_conversion = :mv" if model_version else ""
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
        tiers.append(
            TierAccuracy(
                tier=tier_name,
                total_leads=total_in_tier,
                converted=converted,
                precision=precision,
                avg_score=round(float(row[2] or 0), 1),
                avg_deal_value=round(float(row[3]), 2) if row[3] else None,
                avg_days_to_close=round(float(row[4]), 1) if row[4] else None,
            )
        )

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
        generated_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Score distribution histogram
# ---------------------------------------------------------------------------


@router.get("/score-distribution", dependencies=[ViewerRequired])
def score_distribution(
    db: Annotated[Session, Depends(get_db)],
    buckets: int = Query(10, ge=5, le=20),
):
    """Return a histogram of the latest live lead score of each contact, in equal-width buckets (the last one runs up to 100)."""
    bucket_size = 100 // buckets
    rows = db.execute(
        text(
            """
            SELECT LEAST(ls.lead_score / :size, :last) AS bucket, COUNT(*) AS n
            FROM lead_scores ls
            INNER JOIN (
                SELECT contact_id, MAX(scored_at) AS max_sa
                FROM lead_scores
                WHERE is_shadow = false
                GROUP BY contact_id
            ) latest ON ls.contact_id = latest.contact_id AND ls.scored_at = latest.max_sa
            WHERE ls.is_shadow = false
            GROUP BY bucket
            """
        ),
        {"size": bucket_size, "last": buckets - 1},
    ).fetchall()

    counts = {int(bucket): n for bucket, n in rows}
    total = sum(counts.values())
    if not total:
        return {"buckets": [], "total": 0}

    histogram = [
        {
            "range": f"{i * bucket_size}-{100 if i == buckets - 1 else (i + 1) * bucket_size - 1}",
            "count": counts.get(i, 0),
        }
        for i in range(buckets)
    ]
    return {"buckets": histogram, "total": total}
