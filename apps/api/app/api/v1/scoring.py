import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import AnalystRequired, ViewerRequired
from app.config import get_settings
from app.database import get_db
from app.models.contact import Contact, ContactFeature
from app.models.company import Company
from app.models.scoring import LeadScore, ScoringRun, ScoringRunStatus
from app.schemas.common import PaginatedResponse
from app.schemas.scoring import (
    LeadScoreRead,
    RankedLeadRead,
    ScoreSimulateRequest,
    ScoreSimulateResponse,
    ScoringRunCreate,
    ScoringRunRead,
)
from app.services.scoring_engine import FeatureVector, score_contact

router = APIRouter()
settings = get_settings()


@router.get("/leads", response_model=PaginatedResponse[RankedLeadRead], dependencies=[ViewerRequired])
def get_ranked_leads(
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    priority_tier: str | None = Query(None, description="HOT | WARM | COOL | COLD"),
    model_version: str | None = Query(None),
    min_score: int | None = Query(None, ge=0, le=100),
    company_id: str | None = Query(None),
):
    """Return the latest score per contact, ranked highest first."""
    # Subquery: latest score per contact
    latest = (
        select(LeadScore.contact_id, func.max(LeadScore.scored_at).label("max_scored_at"))
        .group_by(LeadScore.contact_id)
        .subquery()
    )
    q = (
        select(LeadScore, Contact, Company)
        .join(latest, (LeadScore.contact_id == latest.c.contact_id) & (LeadScore.scored_at == latest.c.max_scored_at))
        .join(Contact, LeadScore.contact_id == Contact.id)
        .outerjoin(Company, Contact.company_id == Company.id)
        .where(LeadScore.is_shadow == False)  # noqa: E712
        .order_by(LeadScore.lead_score.desc())
    )

    if priority_tier:
        q = q.where(LeadScore.priority_tier == priority_tier.upper())
    if model_version:
        q = q.where(LeadScore.model_version == model_version)
    if min_score is not None:
        q = q.where(LeadScore.lead_score >= min_score)
    if company_id:
        q = q.where(Contact.company_id == company_id)

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.execute(q.offset((page - 1) * page_size).limit(page_size)).all()

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
        for score, contact, company in rows
    ]

    return PaginatedResponse(
        items=items,
        total=total or 0,
        page=page,
        page_size=page_size,
        pages=max(1, -(-( total or 0) // page_size)),
    )


@router.post("/simulate", response_model=ScoreSimulateResponse)
def simulate_score(body: ScoreSimulateRequest):
    """What-if scoring: compute score for an arbitrary feature vector without persisting."""
    features = FeatureVector(**body.model_dump())
    result = score_contact(features)
    return ScoreSimulateResponse(
        lead_score=result.lead_score,
        priority_tier=result.priority_tier,
        score_reason=result.score_reason,
        feature_contributions=result.feature_contributions,
        model_version=result.model_version,
    )


@router.post("/runs", response_model=ScoringRunRead, status_code=status.HTTP_202_ACCEPTED, dependencies=[AnalystRequired])
def trigger_scoring_run(
    body: ScoringRunCreate,
    db: Annotated[Session, Depends(get_db)],
):
    """Enqueue a batch scoring run via Celery."""
    run = ScoringRun(
        id=str(uuid.uuid4()),
        model_version=settings.scoring_model_version,
        status=ScoringRunStatus.PENDING,
        filter_segment=body.filter_segment,
        is_shadow=body.is_shadow,
        triggered_by="api",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Dispatch async task
    try:
        from workers.tasks.scoring import run_scoring_batch
        run_scoring_batch.delay(run_id=run.id, filter_segment=body.filter_segment, is_shadow=body.is_shadow)
    except Exception:
        pass  # Celery not available in all environments

    return run


@router.get("/runs", response_model=list[ScoringRunRead], dependencies=[ViewerRequired])
def list_runs(db: Annotated[Session, Depends(get_db)], limit: int = Query(20, ge=1, le=100)):
    runs = db.scalars(select(ScoringRun).order_by(ScoringRun.started_at.desc()).limit(limit)).all()
    return list(runs)


@router.get("/runs/{run_id}", response_model=ScoringRunRead, dependencies=[ViewerRequired])
def get_run(run_id: str, db: Annotated[Session, Depends(get_db)]):
    run = db.get(ScoringRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run
